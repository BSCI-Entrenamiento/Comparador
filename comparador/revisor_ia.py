"""Revisión opcional de los casos dudosos con Claude.

Solo revisa coincidencias "Similar" y "Sin coincidencia" que tengan candidatos parciales.
Las decisiones se guardan en caché: en corridas siguientes solo se consulta lo nuevo.
"""
import hashlib
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

import config
from comparador import emparejador as em
from comparador.modelos import Coincidencia, Producto

log = logging.getLogger(__name__)

SISTEMA = """Eres analista de precios de una tienda de computadoras en Guatemala. \
Comparas una laptop de nuestra tienda (Imeqmo) con candidatos de un competidor y decides si alguno \
es el mismo producto.

Niveles:
- "exacto": mismo modelo y misma configuración (CPU, RAM, almacenamiento, GPU y tamaño de pantalla). \
Diferencias de color, idioma del teclado o edición de Windows (Home/Pro) no impiden "exacto", pero menciónalas.
- "equivalente": no es idéntico, pero es comparable en precio. Debe cumplir TODO esto: \
mismo tamaño de pantalla (±0.5"), la misma RAM, el mismo tipo de GPU (ambas integradas o ambas dedicadas), \
el mismo segmento (oficina, consumo, empresarial o gaming) y como máximo UNA diferencia entre: CPU, \
almacenamiento o modelo de GPU. Puede ser el mismo modelo con otra configuración o un modelo distinto, \
de la misma marca o de otra.
- "distinto": ningún candidato cumple lo anterior. Ante la duda, elige "distinto": es mejor no comparar \
que comparar contra un producto que confunda el análisis de precios.

Un producto de otra marca nunca es "exacto". Si hay candidatos comparables de la misma marca y de otra \
marca, prefiere el de la misma marca; en las diferencias menciona siempre cuando la marca es otra.

Los títulos de las tiendas son abreviados e inconsistentes (por ejemplo "U5-225U" = Intel Core Ultra 5 225U, \
"R7" = AMD Ryzen 7). Usa números de parte y códigos de modelo cuando existan. Si no estás seguro, \
elige el nivel más bajo. Escribe "diferencias" en español, en una frase breve orientada al precio."""

# Para categorías sin especificaciones de cómputo (accesorios, UPS, toner, redes, audio, etc.).
SISTEMA_GENERAL = """Eres analista de precios de una tienda de tecnología en Guatemala. \
Comparas un producto de nuestra tienda (Imeqmo) con candidatos de un competidor y decides si alguno \
es el mismo producto o uno comparable en precio.

Niveles:
- "exacto": el mismo producto: mismo fabricante y mismo modelo o número de parte. Diferencias de color, \
empaque o versión regional no impiden "exacto", pero menciónalas. Un número de modelo distinto con otra \
capacidad, potencia, tamaño o cantidad NO es exacto.
- "equivalente": no es idéntico, pero un cliente lo compararía en precio: el mismo tipo de producto, \
del mismo segmento y con las características principales iguales o casi iguales (por ejemplo capacidad, \
potencia, tamaño, velocidad, conectividad, rendimiento de páginas o cantidad). Puede ser de otra marca.
- "distinto": ningún candidato cumple lo anterior. Ante la duda, elige "distinto": es mejor no comparar \
que comparar contra un producto que confunda el análisis de precios.

Un producto de otra marca nunca es "exacto". Si hay candidatos comparables de la misma marca y de otra \
marca, prefiere el de la misma marca; en las diferencias menciona siempre cuando la marca es otra. \
Un producto reacondicionado o usado nunca es "exacto" de uno nuevo.

Los títulos de las tiendas son abreviados e inconsistentes. Usa números de parte y códigos de modelo \
cuando existan. Escribe "diferencias" en español, en una frase breve orientada al precio."""


def _sistema(im: Producto) -> str:
    return SISTEMA_GENERAL if im.specs.get("modo") == "general" else SISTEMA


class Decision(BaseModel):
    candidato: int | None = Field(description="Número del candidato elegido (1..N) o null si ninguno es comparable")
    nivel: Literal["exacto", "equivalente", "distinto"]
    diferencias: str = Field(description="Frase breve en español con las diferencias relevantes, o 'ninguna'")
    confianza: float = Field(description="Confianza entre 0 y 1")


def _describir(p: Producto, con_specs: bool = True) -> str:
    s = p.specs
    datos = [
        f"título: {p.nombre}",
        f"precio: Q{p.precio:,.2f}" if p.precio else "precio: ?",
        f"marca: {s.get('marca') or '?'}",
    ]
    if con_specs:
        datos += [
            f"cpu: {s.get('cpu') or '?'}",
            f"ram_gb: {s.get('ram') or '?'}",
            f"almacenamiento_gb: {s.get('almacenamiento') or '?'}",
            f"pantalla: {s.get('pantalla') or '?'}",
            f"gpu: {s.get('gpu') or 'no indica'}",
        ]
    elif p.categoria:
        datos.append(f"categoría en la tienda: {p.categoria_nombre or p.categoria}")
    for etiqueta, valor in (("no_parte", p.no_parte if p.tienda == "Imeqmo" else ""),
                            ("codigo_interno", s.get("codigo_interno", "")), ("mpn", p.mpn), ("upc", p.upc)):
        if valor:
            datos.append(f"{etiqueta}: {valor}")
    return "\n".join("  " + d for d in datos)


def _prompt(im: Producto, tienda: str, candidatos: list) -> str:
    con_specs = im.specs.get("modo") != "general"
    partes = [f"Producto de Imeqmo:\n{_describir(im, con_specs)}", f"\nCandidatos de {tienda}:"]
    for i, (nivel, puntaje, comp, motivo, _) in enumerate(candidatos, 1):
        partes.append(f"\n[{i}] (reglas: {nivel}, puntaje {puntaje:.0f}, {motivo})\n{_describir(comp, con_specs)}")
    partes.append("\n¿Cuál candidato corresponde al producto de Imeqmo?")
    return "\n".join(partes)


def _clave(im: Producto, tienda: str, candidatos: list) -> str:
    # Incluye el criterio (prompt) y el modelo: si cambian, las decisiones guardadas ya no aplican.
    base = [_sistema(im), config.IA_MODELO, config.IA_EFFORT, im.url, im.nombre, tienda]
    base += [f"{c.url}|{c.nombre}|{c.precio}" for _, _, c, _, _ in candidatos]
    return hashlib.sha1("\n".join(base).encode("utf-8")).hexdigest()


class RevisorIA:
    def __init__(self, ruta_cache: Path):
        self.ruta_cache = ruta_cache
        self.cache = json.loads(ruta_cache.read_text(encoding="utf-8")) if ruta_cache.exists() else {}
        self.cliente = None
        self.activo = False
        self.consultas = 0
        self.desde_cache = 0
        self.tokens_entrada = 0
        self.tokens_salida = 0
        self.errores = 0
        self.omitidas_por_tope = 0
        self._lock = threading.Lock()
        try:
            import anthropic

            self._anthropic = anthropic
            self.cliente = anthropic.Anthropic(max_retries=4)
            self.activo = True
        except Exception as e:  # sin SDK o sin credenciales
            log.warning("IA desactivada: %s", e)

    @staticmethod
    def necesita_revision(c: Coincidencia) -> bool:
        if c.nivel in em.SIMILARES:
            return True
        return c.nivel == em.SIN and bool(c.candidatos) and c.motivo != "Corrección manual: no existe"

    def _consultar(self, prompt: str, sistema: str) -> Decision | None:
        esquema = self._anthropic.transform_schema(Decision.model_json_schema())
        resp = self.cliente.beta.messages.create(
            model=config.IA_MODELO,
            max_tokens=config.IA_MAX_TOKENS,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": config.IA_EFFORT, "format": {"type": "json_schema", "schema": esquema}},
            system=sistema,
            messages=[{"role": "user", "content": prompt}],
        )
        with self._lock:
            self.consultas += 1
            self.tokens_entrada += resp.usage.input_tokens or 0
            self.tokens_salida += resp.usage.output_tokens or 0
        if resp.stop_reason == "refusal":
            log.warning("La IA declinó una consulta (%s)", getattr(resp.stop_details, "category", None))
            return None
        if resp.stop_reason == "max_tokens":
            log.warning("Respuesta de IA truncada (max_tokens)")
            return None
        texto = "".join(b.text for b in resp.content if b.type == "text")
        try:
            return Decision.model_validate_json(texto)
        except ValidationError as e:
            log.warning("Respuesta de IA inválida: %s", e)
            return None

    def _decidir(self, im: Producto, tienda: str, candidatos: list, clave: str) -> Decision | None:
        """Consulta a la IA y guarda la decisión. None si no se pudo (la coincidencia queda como está)."""
        if not self.activo:
            return None
        try:
            decision = self._consultar(_prompt(im, tienda, candidatos), _sistema(im))
        except self._anthropic.AuthenticationError as e:
            log.warning("IA desactivada (credenciales inválidas): %s", e)
            self.activo = False
            return None
        except self._anthropic.APIConnectionError as e:
            log.warning("Sin conexión con la API de IA: %s", e)
            with self._lock:
                self.errores += 1
            return None
        except self._anthropic.APIStatusError as e:
            log.warning("Error de la API de IA (%s): %s", e.status_code, e)
            with self._lock:
                self.errores += 1
            return None
        except Exception as e:  # p. ej. sin credenciales: el SDK lanza TypeError al consultar
            if "authentication method" in str(e):
                log.warning("IA desactivada: falta ANTHROPIC_API_KEY (pégala en el archivo .env)")
            else:
                log.warning("IA desactivada para esta corrida: %s", e)
            self.activo = False
            return None
        if decision is None:
            with self._lock:
                self.errores += 1
            return None
        with self._lock:
            self.cache[clave] = decision.model_dump()
        return decision

    def revisar(self, im: Producto, tienda: str, c: Coincidencia) -> Coincidencia:
        """Revisa un solo caso (ver revisar_todas para muchos en paralelo)."""
        return self.revisar_todas([(im, tienda, c)])[0]

    def revisar_todas(self, casos: list[tuple[Producto, str, Coincidencia]]) -> list[Coincidencia]:
        """Revisa los casos dudosos: primero la caché; los nuevos, en paralelo y hasta IA_MAX_CONSULTAS."""
        resultado = [c for _, _, c in casos]
        if not self.activo:
            return resultado
        pendientes = []  # (posición, im, tienda, candidatos, clave)
        for pos, (im, tienda, c) in enumerate(casos):
            if not self.necesita_revision(c):
                continue
            candidatos = c.candidatos[: config.IA_MAX_CANDIDATOS]
            clave = _clave(im, tienda, candidatos)
            guardado = self.cache.get(clave)
            if guardado:
                self.desde_cache += 1
                resultado[pos] = aplicar(c, Decision.model_validate(guardado), candidatos, im)
            else:
                pendientes.append((pos, im, tienda, candidatos, clave))

        if len(pendientes) > config.IA_MAX_CONSULTAS:
            self.omitidas_por_tope = len(pendientes) - config.IA_MAX_CONSULTAS
            log.warning("IA: %d casos nuevos superan el tope de %d consultas; %d quedan para la próxima corrida",
                        len(pendientes), config.IA_MAX_CONSULTAS, self.omitidas_por_tope)
            pendientes = pendientes[: config.IA_MAX_CONSULTAS]
        if pendientes:
            log.info("IA: %d consultas nuevas (%d desde caché)...", len(pendientes), self.desde_cache)

        hechas = [0]

        def tarea(item):
            pos, im, tienda, candidatos, clave = item
            decision = self._decidir(im, tienda, candidatos, clave)
            with self._lock:
                hechas[0] += 1
                if hechas[0] % 50 == 0:
                    self._guardar()
                    log.info("  IA: %d de %d...", hechas[0], len(pendientes))
            if decision is not None:
                resultado[pos] = aplicar(casos[pos][2], decision, candidatos, im)

        with ThreadPoolExecutor(max_workers=config.IA_HILOS) as ejecutor:
            list(ejecutor.map(tarea, pendientes))
        if pendientes:
            with self._lock:
                self._guardar()
        return resultado

    def _guardar(self):
        self.ruta_cache.parent.mkdir(parents=True, exist_ok=True)
        self.ruta_cache.write_text(json.dumps(self.cache, ensure_ascii=False, indent=1), encoding="utf-8")

    def resumen(self) -> str:
        if not self.activo and not self.consultas:
            return "IA: desactivada (sin credenciales o sin conexión); se usaron solo las reglas"
        texto = (f"IA: {self.consultas} consultas nuevas, {self.desde_cache} desde caché, "
                 f"{self.errores} con error, tokens entrada/salida {self.tokens_entrada:,}/{self.tokens_salida:,}")
        if self.omitidas_por_tope:
            texto += f", {self.omitidas_por_tope} pendientes por el tope IA_MAX_CONSULTAS"
        return texto


def aplicar(c: Coincidencia, d: Decision, candidatos: list, im: Producto | None = None) -> Coincidencia:
    """Aplica la decisión de la IA a la coincidencia de las reglas."""
    nota = f"{d.diferencias} (confianza {d.confianza:.0%})"
    if d.nivel == "distinto" or not d.candidato or not (1 <= d.candidato <= len(candidatos)):
        return Coincidencia(None, em.SIN, c.puntaje, "IA: ningún candidato comparable",
                            nota_ia=nota, candidatos=c.candidatos)
    _, puntaje, comp, motivo, difs = candidatos[d.candidato - 1]
    otra_marca = im is not None and im.specs.get("marca") != comp.specs.get("marca")
    con_specs = im is not None and im.specs.get("modo") != "general"
    if con_specs:
        # Control obligatorio: la IA no puede saltarse el criterio de "Similar".
        estado = em.comparar_specs(im.specs, comp.specs)
        motivos = em.diferencias_mayores(im.specs, comp.specs, estado)
        if otra_marca:  # igual que en las reglas: otra marca solo con la misma configuración
            distintos = [c for c in ("cpu", "ram", "almacenamiento", "gpu") if estado[c] == "distinto"]
            if distintos and not motivos:
                motivos = [f"otra marca con otra configuración ({', '.join(distintos)})"]
        if motivos:
            return Coincidencia(None, em.SIN, c.puntaje,
                                f"IA propuso '{d.nivel}', descartado por criterio: {', '.join(motivos)}",
                                nota_ia=f"propuso '{comp.nombre[:60]}', descartado por criterio "
                                        f"({', '.join(motivos)}). {nota}",
                                candidatos=c.candidatos)
    nivel = em.EXACTO_IA if d.nivel == "exacto" else em.SIMILAR_IA
    if nivel == em.EXACTO_IA and otra_marca:
        nivel = em.SIMILAR_IA  # un producto de otra marca nunca cuenta como exacto
    if nivel == em.EXACTO_IA and em.es_reacondicionado(comp):
        nivel = em.SIMILAR_IA
    if nivel == em.EXACTO_IA and d.confianza < config.IA_CONFIANZA_EXACTO:
        nivel = em.SIMILAR_IA  # p. ej. otro color o sin número de parte que lo confirme
        nota = f"{nota}; no cuenta como exacto: confianza menor a {config.IA_CONFIANZA_EXACTO:.0%}"
    if nivel == em.EXACTO_IA and con_specs and im.specs.get("tactil") != comp.specs.get("tactil"):
        nivel = em.SIMILAR_IA  # táctil vs. no táctil cambia el precio: no es el mismo producto
        nota = f"{nota}; no cuenta como exacto: táctil vs. no táctil"
    return Coincidencia(comp, nivel, puntaje, f"IA (reglas: {motivo})", difs, nota_ia=nota, candidatos=c.candidatos)

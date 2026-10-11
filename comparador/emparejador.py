"""Emparejamiento de cada producto de Imeqmo con los catálogos de la competencia.

Dos modos, según la categoría de Imeqmo:
- "specs" (laptops, computadoras): compara CPU, RAM, almacenamiento, pantalla y GPU.
- "general" (el resto): compara por identificadores (UPC, número de parte, código de modelo)
  y por similitud de título; los casos dudosos los decide la IA.
"""
import csv
import re
from collections import defaultdict
from pathlib import Path

import config
from comparador import specs as sp
from comparador.modelos import Coincidencia, Producto

EXACTO_MANUAL = "Exacto (manual)"
EXACTO_ID = "Exacto (no. de parte)"
EXACTO_CONFIG = "Exacto (modelo + config.)"
EXACTO_IA = "Exacto (IA)"
SIMILAR_CONFIG = "Similar (mismo modelo, otra config.)"
SIMILAR_MODELO = "Similar (mismo código de modelo)"
SIMILAR_SPECS = "Similar (mismas specs)"
SIMILAR_OTRA_MARCA = "Similar (otra marca, mismas specs)"
SIMILAR_IA = "Similar (IA)"
SIN = "Sin coincidencia"

EXACTOS = {EXACTO_MANUAL, EXACTO_ID, EXACTO_CONFIG, EXACTO_IA}
SIMILARES = {SIMILAR_CONFIG, SIMILAR_MODELO, SIMILAR_SPECS, SIMILAR_OTRA_MARCA, SIMILAR_IA}
_RANGO = {EXACTO_MANUAL: 6, EXACTO_ID: 5, EXACTO_CONFIG: 4, EXACTO_IA: 4, SIMILAR_CONFIG: 3,
          SIMILAR_MODELO: 3, SIMILAR_SPECS: 2, SIMILAR_IA: 2, SIMILAR_OTRA_MARCA: 1, SIN: 0}

MAX_CANDIDATOS = 5
PUNTAJE_MIN_CANDIDATO = 30
PENALIZACION_OTRA_MARCA = 10  # para que un parecido parcial de otra marca rara vez llegue a candidato
_REACONDICIONADO = re.compile(r"REFURBISHED|REACONDICIONAD|RECERTIFICAD|OPEN BOX|SEMINUEV|USAD[OA]\b")


def es_reacondicionado(p: Producto) -> bool:
    return bool(_REACONDICIONADO.search(sp.normalizar(p.nombre)))


# ------------------------------------------------------------ preparación
def preparar(p: Producto, es_imeqmo: bool = False) -> Producto:
    """Calcula specs y claves de identidad una sola vez por producto."""
    s = sp.extraer(p.nombre, p.marca, "" if es_imeqmo else p.texto)
    # Claves de identidad: números de parte reales. En la competencia solo el MPN
    # (el código de Intelaf es interno y no identifica al producto del fabricante).
    fuentes = (p.no_parte, p.specs.get("codigo_interno", "")) if es_imeqmo else (p.mpn,)
    claves = set()
    for codigo in fuentes:
        c = sp.compacto(codigo)
        if len(c) >= 5:
            claves.add(c)
        partes = [sp.compacto(x) for x in sp.normalizar(codigo).replace("#", "-").split("-")]
        # "D5CD0UA-ABA" -> también "D5CD0UA" (el sufijo es solo la región/idioma)
        if len(partes) > 1 and len(partes[0]) >= 6 and all(len(x) <= 3 for x in partes[1:]):
            claves.add(partes[0])
    s["claves"] = claves
    s["codigos"] = s["codigos"] | {c for c in claves if sp._es_codigo(c)}
    s["blob"] = sp.compacto(" ".join([p.nombre, p.texto, p.no_parte, p.mpn]))
    s["tokens"] = {sp.compacto(t) for t in sp.normalizar(" ".join([p.nombre, p.texto, p.mpn])).split()}
    # Sin categoría (p. ej. pruebas con catálogos de laptops) se asume el modo por especificaciones.
    s["modo"] = "specs" if (not p.categoria or p.categoria.startswith(config.CATEGORIAS_CON_SPECS)) else "general"
    p.specs.update(s)
    return p


class IndiceTienda:
    """Índices del catálogo de una tienda para encontrar candidatos sin comparar contra todo."""

    def __init__(self, productos: list[Producto]):
        self.productos = productos
        self.por_upc = defaultdict(list)
        self.por_marca = defaultdict(list)
        self.por_token = defaultdict(list)
        self.computo = []
        for i, p in enumerate(productos):
            if p.upc:
                self.por_upc[p.upc.lstrip("0")].append(i)
            if p.specs.get("marca"):
                self.por_marca[p.specs["marca"]].append(i)
            for t in p.specs["tokens"]:
                if len(t) >= 4:
                    self.por_token[t].append(i)
            if p.specs.get("es_computo"):
                self.computo.append(i)
        self.titulos = sp.IndiceTitulos([p.specs["palabras"] for p in productos])

    def candidatos(self, im: Producto) -> dict[int, float]:
        """{índice: similitud de título} de los productos que vale la pena evaluar."""
        s = im.specs
        ids = dict(self.titulos.similares(s["palabras"], k=25))
        extra = set()
        if im.upc:
            extra.update(self.por_upc.get(im.upc.lstrip("0"), ()))
        for clave in s["claves"]:
            if len(clave) >= 7:
                extra.update(i for i, p in enumerate(self.productos) if clave in p.specs["blob"])
            else:
                extra.update(self.por_token.get(clave, ()))
        if s.get("marca"):
            extra.update(self.por_marca.get(s["marca"], ()))
        if s.get("modo") == "specs":
            extra.update(self.computo)
        for i in extra:
            ids.setdefault(i, 0.0)
        return ids


# ------------------------------------------------------------ comparaciones
def _identidad(a: Producto, b: Producto) -> str:
    """Motivo si a (Imeqmo) y b son el mismo producto por UPC / no. de parte / MPN."""
    if a.upc and b.upc and a.upc.lstrip("0") == b.upc.lstrip("0"):
        return f"UPC {a.upc}"
    for clave in a.specs["claves"]:
        if (len(clave) >= 7 and clave in b.specs["blob"]) or clave in b.specs["tokens"]:
            return f"no. de parte {clave}"
    for clave in b.specs["claves"]:
        if len(clave) >= 7 and (clave in a.specs["claves"] or clave in a.specs["blob"]):
            return f"no. de parte {clave}"
    return ""


def _codigo_comun(a: Producto, b: Producto) -> str:
    for ca in a.specs["codigos"]:
        if len(ca) >= 7 and ca in b.specs["blob"]:
            return ca
        for cb in b.specs["codigos"]:
            if ca == cb or (min(len(ca), len(cb)) >= 7 and (ca in cb or cb in ca)):
                return ca if len(ca) <= len(cb) else cb
    return ""


def comparar_specs(a: dict, b: dict) -> dict:
    estado = {"cpu": sp.comparar_cpu(a["cpu"], b["cpu"])}
    for campo in ("ram", "almacenamiento"):
        if a[campo] is None or b[campo] is None:
            estado[campo] = "desconocido"
        else:
            estado[campo] = "igual" if a[campo] == b[campo] else "distinto"
    if a["pantalla"] is None or b["pantalla"] is None:
        estado["pantalla"] = "desconocido"
    else:
        estado["pantalla"] = "igual" if abs(a["pantalla"] - b["pantalla"]) <= 0.35 else "distinto"
    if a["gpu"] and b["gpu"]:
        estado["gpu"] = "igual" if a["gpu"] == b["gpu"] else "distinto"
    else:
        estado["gpu"] = "desconocido"
    return estado


def _gb(v):
    if v is None:
        return "?"
    return f"{v // 1024} TB" if v >= 1024 and v % 1024 == 0 else f"{v} GB"


def describir_diferencias(a: dict, b: dict, estado: dict) -> str:
    etiquetas = {"cpu": "CPU", "ram": "RAM", "almacenamiento": "Almac.", "pantalla": "Pantalla", "gpu": "GPU"}
    partes = []
    for campo, e in estado.items():
        if e != "distinto":
            continue
        va, vb = a[campo], b[campo]
        if campo in ("ram", "almacenamiento"):
            va, vb = _gb(va), _gb(vb)
        partes.append(f"{etiquetas[campo]} {va} → {vb}")
    return "; ".join(partes)


_PESOS = {"cpu": 25, "ram": 8, "almacenamiento": 8, "pantalla": 4, "gpu": 8}
_ETIQUETAS = {"cpu": "CPU", "almacenamiento": "almacenamiento", "gpu": "GPU"}


def diferencias_mayores(a: dict, b: dict, estado: dict | None = None) -> list[str]:
    """Motivos por los que dos laptops NO son comparables como 'Similar'.

    Criterio: misma pantalla, misma RAM, no mezclar GPU integrada con dedicada y
    como máximo una diferencia entre CPU, almacenamiento o modelo de GPU.
    Solo cuentan diferencias conocidas (un dato que falta no descarta).
    """
    estado = estado or comparar_specs(a, b)
    motivos = []
    if estado["pantalla"] == "distinto":
        motivos.append("otra pantalla")
    if estado["ram"] == "distinto":
        motivos.append("otra RAM")
    tipos_gpu = {"INTEGRADA" if g == "INTEGRADA" else "DEDICADA" for g in (a["gpu"], b["gpu"]) if g}
    if len(tipos_gpu) == 2:
        motivos.append("GPU integrada vs. dedicada")
    otras = [c for c in ("cpu", "almacenamiento", "gpu") if estado[c] == "distinto"]
    if len(otras) > 1:
        motivos.append("más de una diferencia (" + ", ".join(_ETIQUETAS[c] for c in otras) + ")")
    return motivos


def evaluar(im: Producto, comp: Producto, similitud: float = 0.0) -> tuple[str, float, str, str]:
    """(nivel, puntaje, motivo, diferencias) de un candidato. `similitud`: coseno de los títulos."""
    if im.specs.get("modo") == "general":
        return _evaluar_general(im, comp, similitud)
    a, b = im.specs, comp.specs
    estado = comparar_specs(a, b)
    difs = describir_diferencias(a, b, estado)
    iguales = sum(1 for e in estado.values() if e == "igual")
    distintos = [c for c, e in estado.items() if e == "distinto"]

    ident = _identidad(im, comp)
    if ident:
        return EXACTO_ID, 100.0, f"Coincide {ident}", difs

    misma_marca = bool(a["marca"]) and a["marca"] == b["marca"]
    marca_distinta = bool(a["marca"] and b["marca"]) and not misma_marca
    if not misma_marca:
        cambio = f"Marca {a['marca'] or '?'} → {b['marca'] or '?'}"
        difs = f"{cambio}; {difs}" if difs else cambio

    # Un código de modelo compartido solo cuenta dentro de la misma marca
    # (entre marcas distintas suele ser una coincidencia sin significado).
    codigo = "" if marca_distinta else _codigo_comun(im, comp)
    if codigo:
        exacto = (estado["cpu"] == "igual"
                  and "igual" in (estado["ram"], estado["almacenamiento"])
                  and not {"cpu", "ram", "almacenamiento", "gpu"} & set(distintos))
        if exacto:
            return EXACTO_CONFIG, 90.0 + iguales, f"Modelo {codigo} y misma CPU/RAM/almacenamiento", difs
        motivos = diferencias_mayores(a, b, estado)
        if motivos:  # queda como candidato (para auditoría), pero no como coincidencia
            return SIN, 40.0, f"Mismo modelo {codigo}, pero {', '.join(motivos)}", difs
        return SIMILAR_CONFIG, 60.0 + 3 * iguales - 5 * len(distintos), f"Mismo modelo {codigo}", difs

    # Si Imeqmo tiene GPU dedicada, el candidato debe declarar la misma; si no la tiene,
    # el candidato no puede tenerla (evita comparar una gamer con una de oficina).
    gpu_dedicada = a["gpu"] not in ("", "INTEGRADA")
    gpu_ok = estado["gpu"] == "igual" if gpu_dedicada else b["gpu"] in ("", "INTEGRADA")
    reacondicionado = bool(_REACONDICIONADO.search(sp.normalizar(comp.nombre)))
    if reacondicionado:
        difs = f"{difs}; Reacondicionado" if difs else "Reacondicionado"
    mismas_specs = (all(estado[c] == "igual" for c in ("cpu", "ram", "almacenamiento"))
                    and estado["pantalla"] != "distinto" and gpu_ok and not reacondicionado)
    if mismas_specs and misma_marca:
        return SIMILAR_SPECS, 70.0 + iguales, "Misma marca, CPU, RAM y almacenamiento", difs
    if mismas_specs:
        return SIMILAR_OTRA_MARCA, 50.0 + iguales, "Otra marca con la misma CPU, RAM y almacenamiento", difs

    puntaje = 10.0 if misma_marca else -PENALIZACION_OTRA_MARCA
    for campo, peso in _PESOS.items():
        if estado[campo] == "igual":
            puntaje += peso
        elif estado[campo] == "distinto":
            puntaje -= peso / 2
    if estado["cpu"] == "desconocido" and a["cpu"] and b["cpu"] and a["cpu"].split("-")[0] == b["cpu"].split("-")[0]:
        puntaje += 8
    return SIN, max(puntaje, 0.0), "Solo parecido parcial", difs


def _evaluar_general(im: Producto, comp: Producto, similitud: float) -> tuple[str, float, str, str]:
    """Productos sin especificaciones comparables (accesorios, UPS, toner, redes...)."""
    a, b = im.specs, comp.specs
    estado = comparar_specs(a, b)
    difs = describir_diferencias(a, b, estado)  # p. ej. capacidad o tamaño distintos
    ident = _identidad(im, comp)
    if ident:
        return EXACTO_ID, 100.0, f"Coincide {ident}", difs

    misma_marca = bool(a["marca"]) and a["marca"] == b["marca"]
    marca_distinta = bool(a["marca"] and b["marca"]) and not misma_marca
    if not misma_marca:
        cambio = f"Marca {a['marca'] or '?'} → {b['marca'] or '?'}"
        difs = f"{cambio}; {difs}" if difs else cambio
    if _REACONDICIONADO.search(sp.normalizar(comp.nombre)):
        difs = f"{difs}; Reacondicionado" if difs else "Reacondicionado"

    codigo = "" if marca_distinta else _codigo_comun(im, comp)
    if codigo:  # sin specs que lo confirmen: queda como Similar y la IA decide si es el mismo
        return SIMILAR_MODELO, 60.0 + 20 * similitud, f"Mismo código de modelo {codigo}", difs
    puntaje = 60 * similitud + (10.0 if misma_marca else -PENALIZACION_OTRA_MARCA)
    return SIN, max(puntaje, 0.0), f"Título parecido ({similitud:.0%})", difs


# ------------------------------------------------------------ correcciones manuales
def cargar_manuales(ruta: Path) -> dict:
    """{(no_parte_imeqmo, tienda): url_competidor | 'NINGUNO'}"""
    manuales = {}
    if not ruta.exists():
        return manuales
    with ruta.open(encoding="utf-8-sig", newline="") as f:
        for fila in csv.DictReader(f):
            np_ = sp.compacto(fila.get("no_parte_imeqmo", ""))
            tienda = (fila.get("tienda") or "").strip().lower()
            url = (fila.get("url_competidor") or "").strip()
            if np_ and tienda and url:
                manuales[(np_, tienda)] = url
    return manuales


# ------------------------------------------------------------ emparejamiento
def _orden(item):
    nivel, puntaje, comp, _, _ = item
    return (_RANGO[nivel], puntaje, bool(comp.disponible), -(comp.precio or 1e12))


def emparejar(im: Producto, catalogo: "list[Producto] | IndiceTienda", tienda: str,
              manuales: dict | None = None) -> Coincidencia:
    """Mejor coincidencia de `im` en una tienda. `catalogo` puede ser la lista completa
    o un IndiceTienda (que limita la evaluación a los candidatos plausibles)."""
    manual = (manuales or {}).get((sp.compacto(im.no_parte), tienda.lower()))
    if isinstance(catalogo, IndiceTienda):
        pares = [(catalogo.productos[i], sim) for i, sim in catalogo.candidatos(im).items()]
        catalogo = catalogo.productos
    else:
        pares = [(c, 0.0) for c in catalogo]
    evaluados = []
    for c, sim in pares:
        nivel, puntaje, motivo, difs = evaluar(im, c, sim)
        evaluados.append((nivel, puntaje, c, motivo, difs))
    evaluados.sort(key=_orden, reverse=True)
    candidatos = [e for e in evaluados if e[0] != SIN or e[1] >= PUNTAJE_MIN_CANDIDATO][:MAX_CANDIDATOS]

    if manual:
        if manual.upper() == "NINGUNO":
            return Coincidencia(None, SIN, motivo="Corrección manual: no existe", candidatos=candidatos)
        elegido = next((c for c in catalogo if c.url.rstrip("/") == manual.rstrip("/")), None)
        if elegido:
            _, _, _, difs = evaluar(im, elegido)
            return Coincidencia(elegido, EXACTO_MANUAL, 100.0, "Corrección manual", difs, candidatos=candidatos)

    if not candidatos or candidatos[0][0] == SIN:
        return Coincidencia(None, SIN, candidatos[0][1] if candidatos else 0.0,
                            "Sin candidato suficiente", candidatos=candidatos)
    nivel, puntaje, comp, motivo, difs = candidatos[0]
    return Coincidencia(comp, nivel, puntaje, motivo, difs, candidatos=candidatos)

"""Uso:  python -m comparador [categorías...] [--sin-ia] [--salida DIR]

Sin categorías compara todas (menos las excluidas en config.FUENTES["imeqmo"]["excluir"]).
Las categorías se indican por el inicio de su nombre en la URL de Imeqmo: laptops, monitores, redes...
"""
import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import config
from config import cargar_env  # noqa: F401  (el .env se carga al importar config)
from comparador import emparejador as em
from comparador import specs as sp
from comparador.detalles import CacheDetalles, aplicar_cache, enriquecer
from comparador.http import nueva_sesion
from comparador.reporte import agregar_historico, generar_excel, precio_comparable
from comparador.tiendas import COMPETIDORES, imeqmo, intelaf

RAIZ = Path(__file__).resolve().parent.parent
log = logging.getLogger("comparador")


def configurar_log(carpeta: Path):
    carpeta.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout),
                  logging.FileHandler(carpeta / "comparador.log", encoding="utf-8")],
    )
    for ruido in ("httpx", "urllib3", "anthropic"):
        logging.getLogger(ruido).setLevel(logging.WARNING)


def _emparejar_tienda(productos_im, indice, tienda, manuales, resultados):
    for p in productos_im:
        resultados.setdefault(p.url, {})[tienda] = em.emparejar(p, indice, tienda, manuales)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m comparador", description="Compara precios de Imeqmo con la competencia.")
    ap.add_argument("categorias", nargs="*",
                    help="inicio del nombre de las categorías de Imeqmo (p. ej. laptops monitores); vacío = todas")
    ap.add_argument("--sin-ia", action="store_true", help="no usar la revisión con IA aunque haya credenciales")
    ap.add_argument("--salida", type=Path, default=RAIZ / "salidas", help="carpeta de salida (default: salidas/)")
    args = ap.parse_args(argv)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    configurar_log(args.salida)
    try:
        ejecutar(args.categorias, args.sin_ia, args.salida)
    except RuntimeError as e:
        log.error("%s", e)
        return 1
    return 0


def ejecutar(categorias: list[str] | None = None, sin_ia: bool = False, salida: Path = RAIZ / "salidas") -> dict:
    """Corre la comparación completa y devuelve un resumen (lo usan la CLI y el flujo de Prefect).

    Lee y escribe el estado (cachés e histórico) en `salida`. Lanza RuntimeError si Imeqmo no responde.
    """
    categorias = list(categorias or [])
    salida.mkdir(parents=True, exist_ok=True)
    inicio = time.time()
    fuentes = config.FUENTES
    sesion = nueva_sesion()
    cache = CacheDetalles(salida / "cache_detalles.json")

    # 1. Catálogos completos de la competencia
    catalogos, errores = {}, {}
    for tienda in config.TIENDAS_COMPETENCIA:
        modulo, clave = COMPETIDORES[tienda]
        try:
            log.info("Descargando catálogo de %s...", tienda)
            productos = modulo.obtener(fuentes[clave], sesion)
            if not productos:
                raise RuntimeError("devolvió 0 productos (¿cambió la URL o el formato del sitio?)")
            aplicar_cache(productos, cache)  # MPN ya conocidos; los nuevos se piden más adelante
            catalogos[tienda] = productos
            log.info("%s: %d productos", tienda, len(productos))
        except Exception as e:
            errores[tienda] = f"{type(e).__name__}: {e}"[:200]
            catalogos[tienda] = []
            log.error("%s no disponible en esta corrida: %s", tienda, errores[tienda])
    # Las marcas declaradas por las tiendas sirven para reconocer marcas en los títulos de Imeqmo
    sp.registrar_marcas({p.marca for lst in catalogos.values() for p in lst if p.marca})
    for tienda in catalogos:
        catalogos[tienda] = [em.preparar(p) for p in catalogos[tienda]]

    # 2. Imeqmo
    alcance = ", ".join(categorias) if categorias else "todas las categorías"
    log.info("Descargando catálogo de Imeqmo (%s)...", alcance)
    productos_im = imeqmo.obtener_todo(fuentes["imeqmo"], sesion, filtro=categorias or None)
    if not productos_im:
        raise RuntimeError("Imeqmo no devolvió productos; se cancela la corrida.")
    n = enriquecer(productos_im, imeqmo, sesion, cache)
    log.info("Imeqmo: %d productos en %d categorías (%d páginas de detalle nuevas)",
             len(productos_im), len({p.categoria for p in productos_im}), n)
    for p in productos_im:
        em.preparar(p, es_imeqmo=True)

    # 3. Emparejamiento por reglas
    manuales = em.cargar_manuales(RAIZ / "coincidencias_manuales.csv")
    resultados = {}
    for tienda in config.TIENDAS_COMPETENCIA:
        if tienda in errores:
            continue
        log.info("Buscando equivalentes en %s...", tienda)
        _emparejar_tienda(productos_im, em.IndiceTienda(catalogos[tienda]), tienda, manuales, resultados)

    # Intelaf publica el MPN solo en la página de cada producto: se pide para los candidatos
    # (una sola vez, queda en caché) y se vuelve a emparejar con ese dato.
    if "Intelaf" in catalogos and "Intelaf" not in errores:
        candidatos = {c.url: c for r in resultados.values() if "Intelaf" in r
                      for _, _, c, _, _ in r["Intelaf"].candidatos}
        n = enriquecer(list(candidatos.values()), intelaf, sesion, cache)
        if n:
            log.info("Intelaf: %d páginas de detalle nuevas; se vuelve a emparejar", n)
            for c in candidatos.values():
                em.preparar(c)
            _emparejar_tienda(productos_im, em.IndiceTienda(catalogos["Intelaf"]), "Intelaf", manuales, resultados)

    # 4. Revisión con IA de los casos dudosos
    revisor = None
    if not sin_ia:
        from comparador.revisor_ia import RevisorIA

        revisor = RevisorIA(salida / "cache_ia.json")
        if revisor.activo:
            log.info("Revisión con IA activa (%s) para los casos dudosos...", config.IA_MODELO)
            casos = [(p, t, c) for p in productos_im for t, c in resultados[p.url].items()]
            for (p, t, _), c in zip(casos, revisor.revisar_todas(casos)):
                resultados[p.url][t] = c

    # 5. Reporte
    resumen_ia = revisor.resumen() if revisor else "IA: no usada (--sin-ia)"
    etiqueta = "-".join(categorias) if categorias else "todas"
    nombre = f"comparacion_{etiqueta}_{datetime.now():%Y-%m-%d_%H%M}.xlsx"
    ruta = generar_excel(salida / nombre, alcance, productos_im, resultados, catalogos, errores, resumen_ia)
    agregar_historico(salida / "historico.csv", productos_im, resultados)

    resumen = {"ruta": ruta, "alcance": alcance, "productos_imeqmo": len(productos_im), "tiendas": {},
               "resumen_ia": resumen_ia, "errores": errores}
    log.info("-" * 60)
    for tienda in config.TIENDAS_COMPETENCIA:
        pares = [(p, resultados.get(p.url, {}).get(tienda)) for p in productos_im]
        exactos = [(p, precio_comparable(c.producto)) for p, c in pares
                   if c and c.producto and c.nivel in em.EXACTOS and precio_comparable(c.producto)]
        datos = {
            "exactos": len(exactos),
            "similares": sum(1 for _, c in pares if c and c.producto and c.nivel in em.SIMILARES),
            "imeqmo_mas_caro": sum(1 for p, precio in exactos if p.precio > precio + 0.5),
            "imeqmo_mas_barato": sum(1 for p, precio in exactos if p.precio < precio - 0.5),
            "disponible": tienda not in errores,
        }
        resumen["tiendas"][tienda] = datos
        estado = "NO DISPONIBLE" if tienda in errores else f"{datos['exactos']} exactos, {datos['similares']} similares"
        log.info("%-14s %s", tienda, estado)
    resumen["segundos"] = round(time.time() - inicio)
    log.info(resumen_ia)
    log.info("Reporte: %s  (%.0f s)", ruta, resumen["segundos"])
    return resumen


if __name__ == "__main__":
    sys.exit(main())

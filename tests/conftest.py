import json
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from comparador import emparejador as em  # noqa: E402
from comparador.tiendas import click, imeqmo, intelaf, macrosistemas  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def _leer(nombre):
    return (FIXTURES / nombre).read_text(encoding="utf-8")


def _enriquecer(productos, cache):
    for p in productos:
        info = cache.get(p.url, {})
        p.upc = p.upc or info.get("upc", "")
        p.mpn = p.mpn or info.get("mpn", "")
        if info.get("codigo"):
            p.specs["codigo_interno"] = info["codigo"]
    return productos


@pytest.fixture(scope="session")
def catalogos():
    """Catálogos reales guardados, enriquecidos con la caché de detalles y preparados."""
    cache = json.loads(_leer("cache_detalles.json"))
    im = _enriquecer(imeqmo.parsear(_leer("imeqmo_listado.html")), cache)
    comp = {
        "Click": click.parsear(json.loads(_leer("click.json")), "https://click.gt/products/"),
        "MacroSistemas": macrosistemas.parsear(json.loads(_leer("macrosistemas.json"))),
        "Intelaf": _enriquecer(intelaf.parsear(json.loads(_leer("intelaf.json")),
                                               "https://www.intelaf.com/precios_stock_detallado/"), cache),
    }
    return (
        {p.no_parte: em.preparar(p, es_imeqmo=True) for p in im},
        {t: [em.preparar(p) for p in lst] for t, lst in comp.items()},
    )


@pytest.fixture
def leer():
    return _leer

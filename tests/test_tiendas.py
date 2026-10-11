import json

from comparador.tiendas import click, imeqmo, intelaf, macrosistemas


def test_imeqmo_listado(leer):
    productos = imeqmo.parsear(leer("imeqmo_listado.html"))
    assert len(productos) == 35
    p = next(x for x in productos if x.no_parte == "83SC007RUS")
    assert p.precio == 13795.0
    assert p.url.startswith("https://imeqmo.com/shop/83sc007rus-laptop-lenovo")
    assert "?" not in p.url


def test_imeqmo_no_parte_desde_slug():
    assert imeqmo.no_parte_desde_slug("/shop/d5cd0ua-aba-laptop-hp-omen-25866?category=2") == "D5CD0UA-ABA"
    assert imeqmo.no_parte_desde_slug("/shop/producto-sin-patron-123") == ""


def test_imeqmo_detalle(leer):
    assert imeqmo.parsear_detalle(leer("imeqmo_detalle.html")) == {"upc": "821844314524", "codigo": "16-BY0015DX"}


def test_click(leer):
    productos = click.parsear(json.loads(leer("click.json")), "https://click.gt/products/")
    assert len(productos) == 74
    p = next(x for x in productos if "16-BY0015DX" in x.nombre)
    assert p.precio == 4499.0 and p.upc == "821844314524" and p.marca == "HP"
    assert p.url.startswith("https://click.gt/products/")


def test_macrosistemas_precio_en_quetzales(leer):
    productos = macrosistemas.parsear(json.loads(leer("macrosistemas.json")))
    assert len(productos) == 83
    p = next(x for x in productos if "16-BY0015D" in x.nombre)
    assert p.precio == 4849.0 and p.upc == "821844314524"
    assert "&#" not in p.nombre


def test_intelaf(leer):
    productos = intelaf.parsear(json.loads(leer("intelaf.json")), "https://www.intelaf.com/precios_stock_detallado/")
    assert len(productos) == 66
    p = next(x for x in productos if x.no_parte == "AS-M1502YA-1A70")
    assert p.precio == 8011.0 and p.precio_alterno == 6499.0 and p.nota_precio == "Promo ASUS"
    assert p.url == "https://www.intelaf.com/precios_stock_detallado/as-m1502ya-1a70"


def test_intelaf_cuerpo_busqueda():
    cuerpo = intelaf.cuerpo_busqueda("notebooks", 2)
    assert cuerpo["CantidadMaxima"] == 100  # con más de 100 la API devuelve 0 productos
    assert cuerpo["Pagina"] == 2 and cuerpo["Categorias"] == ["notebooks"]


def test_intelaf_detalle_mpn(leer):
    assert intelaf.parsear_detalle(leer("intelaf_detalle.html"))["mpn"] == "M1502YA-NJ572W"

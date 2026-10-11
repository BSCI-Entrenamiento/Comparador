"""Pruebas de la comparación en categorías sin especificaciones de cómputo (modo "general")."""
import json
from types import SimpleNamespace

import anthropic

import config
from comparador import emparejador as em
from comparador import specs as sp
from comparador.modelos import Producto
from comparador.revisor_ia import SISTEMA, SISTEMA_GENERAL, Decision, RevisorIA, _sistema, aplicar
from comparador.tiendas import imeqmo, intelaf


def _im(nombre, no_parte, categoria="proteccion-electrica", precio=1000.0):
    p = Producto("Imeqmo", nombre, precio, f"https://imeqmo.com/shop/{no_parte.lower()}-x-1", no_parte=no_parte,
                 categoria=categoria, categoria_nombre=categoria.capitalize())
    return em.preparar(p, es_imeqmo=True)


def _comp(tienda, nombre, precio, marca="", codigo="", upc=""):
    p = Producto(tienda, nombre, precio, f"https://{tienda.lower()}.gt/{abs(hash(nombre))}", no_parte=codigo,
                 marca=marca, upc=upc, texto=codigo)
    return em.preparar(p)


# ---------------------------------------------------------------- marcas y títulos
def test_marca_desde_vocabulario_y_primera_en_el_titulo():
    sp.registrar_marcas(["KLIP XTREME", "TP LINK", "Click", "APC"])
    assert sp.marca("Router TP-Link Archer AX73 Doble Banda") == "TPLINK"
    assert sp.marca("Cargador Klip Xtreme para laptop HP") == "KLIPXTREME"  # la primera que aparece
    assert sp.marca("Mochila HP 15.6 Prelude") == "HP"
    assert sp.canonica_marca("Click") == ""  # nombre de la tienda, no es marca
    assert sp.canonica_marca("Alienware") == "DELL"  # submarca


def test_indice_titulos():
    docs = [sp.palabras(t) for t in ("UPS APC Back-UPS 700VA BE700G3", "Mouse Logitech M190 Negro",
                                     "Router TP-Link Archer AX73")]
    indice = sp.IndiceTitulos(docs)
    mejores = indice.similares(sp.palabras("UPS 700VA APC Back-UPS 6 tomas"))
    assert mejores[0][0] == 0 and mejores[0][1] > 0.5


# ---------------------------------------------------------------- tiendas
def test_no_parte_desde_slug_con_nombre():
    nombre = "Teclado Inalámbrico Logitech Signature K650 Español Grafito"
    href = "/shop/920-010910-teclado-inalambrico-logitech-signature-k650-espanol-grafito-25866?category=58"
    assert imeqmo.no_parte_desde_slug(href, nombre) == "920-010910"


def test_parsear_categorias_excluye_servicios():
    html = ('<a href="/shop/category/laptops-2">Laptops</a><a href="/shop/category/laptops-y-surface-2">Laptops</a>'
            '<a href="/shop/category/servicios-corporativos-132">Servicios</a>'
            '<a href="/shop/category/monitores-324"><span>Monitores</span></a>')
    assert imeqmo.parsear_categorias(html, ("servicios-corporativos",)) == [("laptops-2", "Laptops"),
                                                                            ("monitores-324", "Monitores")]


def test_areas_del_menu_de_intelaf():
    menu = [{"Area": "/precios_stock", "Hijos": [{"Area": "NOTEBOOKS"}, {"Area": "not-15", "Hijos": []}]},
            {"Area": "notebooks"}]
    assert intelaf.areas_del_menu(menu) == ["notebooks", "not-15"]


# ---------------------------------------------------------------- emparejamiento general
def test_modo_por_categoria():
    assert _im("UPS APC 700VA", "BE700G3").specs["modo"] == "general"
    assert _im("Laptop HP 15", "ABC123", categoria="laptops").specs["modo"] == "specs"


def test_exacto_por_numero_de_parte_en_el_titulo():
    sp.registrar_marcas(["APC"])
    ups = _im("UPS 700VA APC Back-UPS BE700G3 6 Tomas Nema", "BE700G3")
    otro = _comp("Intelaf", "UPS Marca APC Modelo BE700G3 700VA (Voltio-Amperio)", 1255.0, "APC", "UPS-APC-BE700G")
    indice = em.IndiceTienda([otro, _comp("Intelaf", "Mouse Logitech M190", 99.0, "LOGITECH", "MOU-LOG-M190")])
    c = em.emparejar(ups, indice, "Intelaf")
    assert c.nivel == em.EXACTO_ID and c.producto is otro


def test_claves_de_identidad_desde_el_numero_de_parte():
    claves = lambda np_: _im("Producto", np_).specs["claves"]  # noqa: E731
    assert claves("D5CD0UA-ABA") == {"D5CD0UAABA", "D5CD0UA"}  # sufijo de región: se quita
    assert claves("KF548S38IB-32") == {"KF548S38IB32"}  # sufijo = capacidad: NO se quita
    assert claves("ARCHER-T2U") == {"ARCHERT2U"}  # "ARCHER" solo no identifica nada
    assert claves("CABLE-DE-RED") == set()  # palabras, no un número de parte


def test_cable_de_red_no_empareja_con_extensor_hdmi():
    sp.registrar_marcas(["MANHATTAN"])
    im = _im("Cable de Red (Metro)", "CABLE-DE-RED", categoria="redes")
    comp = _comp("Intelaf", "MANHATTAN 207539 EXTENSOR HDMI POR CABLE DE RED 1080 60", 600.0, "MANHATTAN")
    assert em.emparejar(im, em.IndiceTienda([comp]), "Intelaf").nivel not in em.EXACTOS


def test_numero_de_parte_debe_coincidir_completo():
    sp.registrar_marcas(["TP LINK"])
    im = _im("Adaptador de Red USB a Wi-Fi TP-Link Archer T2U Doble Banda", "ARCHER-T2U", categoria="redes")
    otro = _comp("Intelaf", "Adaptador USB Marca Tp Link Modelo Archer T2UB Nano AC600", 250.0, "TP LINK")
    mismo = _comp("Intelaf", "Adaptador USB Marca Tp Link Modelo Archer T2U AC600", 220.0, "TP LINK")
    assert em.emparejar(im, em.IndiceTienda([otro]), "Intelaf").nivel not in em.EXACTOS
    assert em.emparejar(im, em.IndiceTienda([otro, mismo]), "Intelaf").producto is mismo


def test_kingston_32gb_no_es_exacto_de_16gb():
    sp.registrar_marcas(["KINGSTON"])
    im = _im("Memoria RAM DDR5 SODIMM 32GB Kingston Fury Impact 4800MHz", "KF548S38IB-32", categoria="componentes")
    comp = _comp("Intelaf", "Memoria RAM DDR5 De 16GB Para Notebook Marca Kingston Fury KF548S38IB-16", 700.0,
                 "KINGSTON")
    assert em.emparejar(im, em.IndiceTienda([comp]), "Intelaf").nivel not in em.EXACTOS


def test_mismo_codigo_de_modelo_queda_similar_para_la_ia():
    sp.registrar_marcas(["AOC"])
    im = _im('Monitor Gaming AOC 24" IPS 24G50F FHD 144Hz', "MON-AOC-X1", categoria="monitores")
    comp = _comp("Click", "MONITOR AOC 24G50F 23.8P 144HZ", 1199.0, "AOC")
    c = em.emparejar(im, em.IndiceTienda([comp]), "Click")
    assert c.nivel == em.SIMILAR_MODELO and c.nivel not in em.EXACTOS


def test_titulo_parecido_de_otra_marca_es_candidato_sin_coincidencia():
    sp.registrar_marcas(["FORZA", "APC"])
    im = _im("UPS 750VA APC Back-UPS 6 Tomas Nema 120V", "BX750X")
    comp = _comp("Intelaf", "UPS Forza 750VA 6 Tomas Nema 120V", 650.0, "FORZA", "UPS-FOR-750")
    c = em.emparejar(im, em.IndiceTienda([comp]), "Intelaf")
    assert c.producto is None and c.candidatos and "Marca APC → FORZA" in c.candidatos[0][4]


def test_indice_incluye_misma_marca_y_upc():
    a = _comp("Click", "Teclado Logitech K650", 300.0, "LOGITECH", upc="097855189974")
    b = _comp("Click", "Bocina JBL Go 4", 400.0, "JBL")
    im = _im("Teclado Inalámbrico Logitech Signature K650", "920-010910", categoria="accesorios-de-computo")
    im.upc = "097855189974"
    candidatos = em.IndiceTienda([a, b]).candidatos(im)
    assert 0 in candidatos and 1 not in candidatos
    assert em.emparejar(im, em.IndiceTienda([a, b]), "Click").nivel == em.EXACTO_ID


# ---------------------------------------------------------------- IA en modo general
def test_ia_general_usa_su_criterio_y_permite_otra_marca():
    im = _im("UPS 750VA APC Back-UPS 6 Tomas", "BX750X")
    comp = _comp("Intelaf", "UPS Forza 750VA 6 Tomas", 650.0, "FORZA")
    assert _sistema(im) == SISTEMA_GENERAL and _sistema(_im("Laptop", "X1", categoria="laptops")) == SISTEMA
    c = em.emparejar(im, em.IndiceTienda([comp]), "Intelaf")
    candidatos = [(em.SIN, 40.0, comp, "título", "")]
    equivalente = aplicar(c, Decision(candidato=1, nivel="equivalente", diferencias="otra marca", confianza=0.8),
                          candidatos, im)
    assert equivalente.nivel == em.SIMILAR_IA and equivalente.producto is comp
    exacto = aplicar(c, Decision(candidato=1, nivel="exacto", diferencias="", confianza=0.8), candidatos, im)
    assert exacto.nivel == em.SIMILAR_IA  # otra marca nunca es exacto


def test_exacto_con_confianza_baja_queda_similar(monkeypatch):
    monkeypatch.setattr(config, "IA_CONFIANZA_EXACTO", 0.90)
    sp.registrar_marcas(["JBL"])
    im = _im("Bocina Bluetooth JBL Flip 7 35W Rosado", "JBLFLIP7PINK", categoria="bocinas")
    comp = _comp("Click", "BOCINA PORTATIL FLIP 7 WATERPROOF BLACK", 1299.0, "JBL")
    c = em.emparejar(im, em.IndiceTienda([comp]), "Click")
    candidatos = [(em.SIN, 50.0, comp, "título", "")]
    color = aplicar(c, Decision(candidato=1, nivel="exacto", diferencias="otro color", confianza=0.85), candidatos, im)
    assert color.nivel == em.SIMILAR_IA and "confianza menor a 90%" in color.nota_ia
    seguro = aplicar(c, Decision(candidato=1, nivel="exacto", diferencias="ninguna", confianza=0.93), candidatos, im)
    assert seguro.nivel == em.EXACTO_IA


class _Falso:
    def __init__(self):
        self.llamadas = 0
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.llamadas += 1
        texto = json.dumps({"candidato": None, "nivel": "distinto", "diferencias": "x", "confianza": 0.5})
        return SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=50),
                               content=[SimpleNamespace(type="text", text=texto)])


def test_revisar_todas_respeta_el_tope(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "IA_MAX_CONSULTAS", 3)
    r = RevisorIA(tmp_path / "c.json")
    r._anthropic, r.cliente, r.activo = anthropic, _Falso(), True
    casos = []
    for i in range(5):
        im = _im(f"UPS {i}00VA APC Back-UPS", f"BX{i}00X")
        comp = _comp("Intelaf", f"UPS Forza {i}00VA", 600.0, "FORZA")
        casos.append((im, "Intelaf", em.emparejar(im, em.IndiceTienda([comp]), "Intelaf")))
    assert all(r.necesita_revision(c) for _, _, c in casos)
    resultado = r.revisar_todas(casos)
    assert len(resultado) == 5 and r.cliente.llamadas == 3 and r.omitidas_por_tope == 2
    assert "pendientes por el tope" in r.resumen()

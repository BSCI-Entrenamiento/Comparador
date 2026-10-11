"""Imeqmo (Odoo eCommerce): se parsea el listado HTML de cada categoría."""
import html as html_lib
import json
import logging
import re
import unicodedata
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from comparador.http import pausa
from comparador.modelos import Producto

TIENDA = "Imeqmo"
BASE = "https://imeqmo.com"
log = logging.getLogger(__name__)


def _slugify(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto)
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def no_parte_desde_slug(href: str, nombre: str = "") -> str:
    """El slug de Odoo es '<referencia>-<nombre>-<id>':
    '/shop/920-010910-teclado-inalambrico-logitech-k650-25866' -> '920-010910'."""
    slug = href.split("/shop/", 1)[-1].split("?", 1)[0]
    base = re.sub(r"-\d+$", "", slug)
    nombre_slug = _slugify(nombre) if nombre else ""
    if nombre_slug and base.endswith("-" + nombre_slug):
        return base[: -len(nombre_slug) - 1].upper()
    m = re.match(r"(.+?)-(?:laptop|notebook|computadora|pc)-", slug)  # respaldo
    return m.group(1).upper() if m else ""


def parsear(html: str) -> list[Producto]:
    soup = BeautifulSoup(html, "lxml")
    productos = []
    for form in soup.select('form[itemtype$="schema.org/Product"]'):
        a = form.select_one('a[itemprop="name"]')
        precio = form.select_one('span[itemprop="price"]')
        if not a or not precio:
            continue
        href = a.get("href", "")
        nombre = re.sub(r"\s+", " ", (a.get("title") or a.get_text()).strip())
        productos.append(
            Producto(
                tienda=TIENDA,
                nombre=nombre,
                precio=float(precio.get_text(strip=True)),
                url=urljoin(BASE, href.split("?", 1)[0]),
                no_parte=no_parte_desde_slug(href, nombre),
            )
        )
    return productos


def parsear_categorias(html: str, excluir=()) -> list[tuple[str, str]]:
    """[(slug, nombre)] de las categorías principales del menú de la tienda."""
    vistos, categorias = set(), []
    for m in re.finditer(r'href="/shop/category/([a-z0-9-]+?)-(\d+)"[^>]*>(.*?)</a>', html, re.S):
        slug, id_, nombre = m[1], m[2], re.sub(r"<[^>]+>", " ", html_lib.unescape(m[3]))
        nombre = re.sub(r"\s+", " ", nombre).strip()
        if id_ in vistos or any(slug.startswith(x) for x in excluir):
            continue
        vistos.add(id_)
        categorias.append((f"{slug}-{id_}", nombre))
    return categorias


def parsear_detalle(html: str) -> dict:
    """Extrae UPC y código interno de la página de producto (data-product-tracking-info)."""
    soup = BeautifulSoup(html, "lxml")
    nodo = soup.select_one("[data-product-tracking-info]")
    if not nodo:
        return {}
    try:
        info = json.loads(nodo["data-product-tracking-info"])
    except ValueError:
        return {}
    item_id = str(info.get("item_id") or "").strip()
    codigo = re.match(r"\[([^\]]+)\]", info.get("item_name") or "")
    return {
        "upc": item_id if re.fullmatch(r"\d{11,14}", item_id) else "",
        "codigo": codigo.group(1).strip() if codigo else "",
    }


def detalle(producto: Producto, sesion) -> dict:
    r = sesion.get(producto.url, timeout=30)
    r.raise_for_status()
    return parsear_detalle(r.text)


def obtener(cfg: dict, sesion) -> list[Producto]:
    """Productos de una categoría (cfg['url'] = URL de la categoría)."""
    todos, vistos = [], set()
    pagina = 1
    while True:
        url = cfg["url"] if pagina == 1 else f"{cfg['url']}/page/{pagina}"
        r = sesion.get(url, params={"ppg": cfg.get("ppg", 100)}, timeout=30)
        r.raise_for_status()
        nuevos = [p for p in parsear(r.text) if p.url not in vistos]
        if not nuevos:
            break
        vistos.update(p.url for p in nuevos)
        todos.extend(nuevos)
        pagina += 1
        pausa()
    return todos


def _clave_categoria(slug: str) -> str:
    """'laptops-2' -> 'laptops' (nombre estable para filtros y configuración)."""
    return re.sub(r"-\d+$", "", slug)


def obtener_todo(cfg: dict, sesion, filtro: list[str] | None = None) -> list[Producto]:
    """Todas las categorías (salvo las excluidas). Si un producto está en varias,
    se queda con la primera según cfg['prioridad']."""
    r = sesion.get(cfg["url_tienda"], params={"ppg": cfg.get("ppg", 100)}, timeout=30)
    r.raise_for_status()
    categorias = parsear_categorias(r.text, cfg.get("excluir", ()))
    prioridad = list(cfg.get("prioridad", ()))
    categorias.sort(key=lambda c: next((i for i, p in enumerate(prioridad)
                                        if _clave_categoria(c[0]).startswith(p)), len(prioridad)))
    if filtro:
        categorias = [c for c in categorias if any(_clave_categoria(c[0]).startswith(f) for f in filtro)]
    productos = {}
    for slug, nombre in categorias:
        try:
            lote = obtener({"url": f"{BASE}/shop/category/{slug}", "ppg": cfg.get("ppg", 100)}, sesion)
        except Exception as e:  # categoría vacía o eliminada (p. ej. 404)
            log.warning("Imeqmo: categoría %s no disponible: %s", slug, e)
            continue
        for p in lote:
            if p.url not in productos:
                p.categoria, p.categoria_nombre = _clave_categoria(slug), nombre
                productos[p.url] = p
    return list(productos.values())

"""Click (Shopify): endpoint público products.json de la colección."""
import re

from comparador.http import pausa
from comparador.modelos import Producto


def _upc(sku) -> str:
    sku = (sku or "").strip()
    return sku if re.fullmatch(r"\d{11,14}", sku) else ""


TIENDA = "Click"


def _float(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def parsear(data: dict, base_producto: str) -> list[Producto]:
    productos = []
    for p in data.get("products", []):
        variantes = p.get("variants") or []
        if not variantes:
            continue
        # Se toma la variante disponible más barata (normalmente solo hay una).
        disponibles = [v for v in variantes if v.get("available")] or variantes
        v = min(disponibles, key=lambda x: _float(x.get("price")) or 0)
        lista = _float(v.get("compare_at_price"))
        precio = _float(v.get("price"))
        cuerpo = re.sub(r"<[^>]+>", " ", p.get("body_html") or "")
        productos.append(
            Producto(
                tienda=TIENDA,
                nombre=p["title"].strip(),
                precio=precio,
                url=base_producto + p["handle"],
                upc=_upc(v.get("sku")),
                marca=(p.get("vendor") or "").strip(),
                precio_lista=lista if lista and precio and lista > precio else None,
                disponible=bool(v.get("available")),
                texto=" ".join([p["handle"], cuerpo, v.get("sku") or ""]),
                categoria=(p.get("product_type") or "").strip(),
            )
        )
    return productos


def obtener(cfg: dict, sesion) -> list[Producto]:
    todos, pagina = [], 1
    while True:
        r = sesion.get(cfg["url"], params={"limit": 250, "page": pagina}, timeout=30)
        r.raise_for_status()
        lote = parsear(r.json(), cfg["base_producto"])
        if not lote:
            break
        todos.extend(lote)
        if len(r.json().get("products", [])) < 250:
            break
        pagina += 1
        pausa()
    return todos

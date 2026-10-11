"""MacroSistemas (WooCommerce): Store API pública."""
import html
import re

from comparador.http import pausa
from comparador.modelos import Producto


def _upc(sku) -> str:
    sku = (sku or "").strip()
    return sku if re.fullmatch(r"\d{11,14}", sku) else ""


TIENDA = "MacroSistemas"


def _monto(valor, unidades_menores: int):
    if valor in (None, ""):
        return None
    return int(valor) / (10**unidades_menores)


def parsear(data: list) -> list[Producto]:
    productos = []
    for p in data:
        precios = p.get("prices") or {}
        menor = int(precios.get("currency_minor_unit", 2))
        precio = _monto(precios.get("price"), menor)
        regular = _monto(precios.get("regular_price"), menor)
        marcas = p.get("brands") or []
        desc = re.sub(r"<[^>]+>", " ", (p.get("short_description") or "") + " " + (p.get("description") or ""))
        productos.append(
            Producto(
                tienda=TIENDA,
                nombre=re.sub(r"\s+", " ", html.unescape(p["name"])).strip(),
                precio=precio,
                url=p["permalink"],
                upc=_upc(p.get("sku")),
                marca=html.unescape(marcas[0]["name"]) if marcas else "",
                precio_lista=regular if regular and precio and regular > precio else None,
                disponible=bool(p.get("is_in_stock")),
                texto=" ".join([p.get("slug", ""), p.get("sku", ""), html.unescape(desc)]),
                categoria=", ".join(html.unescape(c["name"]) for c in p.get("categories") or []),
            )
        )
    return productos


def obtener(cfg: dict, sesion) -> list[Producto]:
    todos, pagina = [], 1
    while True:
        params = {"per_page": 100, "page": pagina}
        if cfg.get("categoria"):  # sin categoría: catálogo completo
            params["category"] = cfg["categoria"]
        r = sesion.get(cfg["url"], params=params, timeout=30)
        r.raise_for_status()
        todos.extend(parsear(r.json()))
        total_paginas = int(r.headers.get("X-WP-TotalPages", 1))
        if pagina >= total_paginas:
            break
        pagina += 1
        pausa()
    return todos

"""Intelaf: API interna que usa su sitio web (máximo 100 productos por página)."""
import json
import re

import config
from comparador.http import nueva_sesion, pausa
from comparador.modelos import Producto

TIENDA = "Intelaf"
POR_PAGINA = 100


def cuerpo_busqueda(area: str, pagina: int) -> dict:
    return {
        "SucursalesCodigo": [],
        "CantidadMaxima": POR_PAGINA,
        "Instruccion": {"nombre": "area", "valor": area},
        "PrecioMenor": 0,
        "PrecioMayor": 0,
        "Acendente": True,
        "Categorias": [area],
        "Marcas": [],
        "Pagina": pagina,
        "Orden": "default",
        "Query": "",
    }


def parsear(data: dict, base_producto: str) -> list[Producto]:
    respuesta = data.get("Response") or {}
    productos = []
    for p in respuesta.get("Productos") or []:
        normal = p.get("PrecioNormal") or None
        descuento = p.get("PrecioDescuento") or None
        anterior = p.get("PrecioAnterior") or None
        existencia = sum((e.get("Existencia") or 0) for e in p.get("Existencia") or [])
        productos.append(
            Producto(
                tienda=TIENDA,
                nombre=p["Descripcion"].strip(),
                precio=normal,
                url=base_producto + p["Codigo"].lower(),
                no_parte=p["Codigo"],
                marca=(p.get("Marca") or "").strip(),
                precio_lista=anterior if anterior and normal and anterior > normal else None,
                precio_alterno=descuento if descuento and normal and descuento < normal else None,
                nota_precio=(p.get("DescripcionDescuento") or "").strip() if descuento else "",
                disponible=existencia > 0 or bool(p.get("EnBodega")),
                texto=p["Codigo"],
                categoria=(p.get("AreaFuncional") or "").strip(),
            )
        )
    return productos


def areas_del_menu(menu) -> list[str]:
    """Códigos de área de todo el menú del sitio (se omiten los enlaces a páginas, que empiezan con '/')."""
    areas = []

    def recorrer(x):
        if isinstance(x, dict):
            a = x.get("Area")
            if isinstance(a, str) and a.strip() and not a.startswith("/"):
                areas.append(a.strip().lower())
            for v in x.values():
                recorrer(v)
        elif isinstance(x, list):
            for v in x:
                recorrer(v)

    recorrer(menu)
    return list(dict.fromkeys(areas))


def obtener(cfg: dict, sesion) -> list[Producto]:
    sesion = nueva_sesion(reintentar_500=False)  # un área inexistente responde 500: no reintentar
    areas = cfg["areas"]
    if areas == "todas":
        r = sesion.get(cfg["url_menu"], headers=config.INTELAF_HEADERS, timeout=30)
        r.raise_for_status()
        areas = areas_del_menu(r.json())
    todos, vistos, fallidas = [], set(), []
    for area in areas:
        pagina = 1
        while True:
            try:
                r = sesion.post(cfg["url"], json=cuerpo_busqueda(area, pagina), headers=config.INTELAF_HEADERS,
                                timeout=30)
                r.raise_for_status()
            except Exception:  # algunas áreas del menú no existen en la API (error 500)
                fallidas.append(area)
                break
            pagina_completa = parsear(r.json(), cfg["base_producto"])
            nuevos = [p for p in pagina_completa if p.no_parte not in vistos]
            vistos.update(p.no_parte for p in nuevos)
            todos.extend(nuevos)
            if len(pagina_completa) < POR_PAGINA:
                break
            pagina += 1
            pausa(cfg.get("pausa"))
        pausa(cfg.get("pausa"))
    if fallidas and len(fallidas) > len(areas) / 2:
        raise RuntimeError(f"fallaron {len(fallidas)} de {len(areas)} áreas")
    return todos


def parsear_detalle(html: str) -> dict:
    """El MPN solo viene en la página de producto (JSON-LD de schema.org)."""
    for bloque in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(bloque)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else [data]:
            if isinstance(d, dict) and d.get("@type") == "Product":
                return {"mpn": (d.get("mpn") or "").strip(), "upc": (d.get("gtin13") or d.get("gtin12") or d.get("gtin") or "").strip()}
    return {}


def detalle(producto: Producto, sesion) -> dict:
    r = sesion.get(producto.url, timeout=30)
    r.raise_for_status()
    return parsear_detalle(r.text)

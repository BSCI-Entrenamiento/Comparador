"""Datos que solo están en la página de cada producto (UPC de Imeqmo, MPN de Intelaf).

Se guardan en una caché local porque no cambian: solo se descargan los productos nuevos,
varios a la vez (config.HILOS_DETALLE).
"""
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import config
from comparador.http import nueva_sesion, pausa
from comparador.modelos import Producto

log = logging.getLogger(__name__)


class CacheDetalles:
    def __init__(self, ruta: Path):
        self.ruta = ruta
        self.datos = {}
        self._lock = threading.Lock()
        if ruta.exists():
            try:
                self.datos = json.loads(ruta.read_text(encoding="utf-8"))
            except ValueError:
                log.warning("Caché de detalles dañada; se regenera: %s", ruta)

    def guardar(self):
        with self._lock:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps(self.datos, ensure_ascii=False, indent=1), encoding="utf-8")


def _aplicar(p: Producto, info: dict):
    p.upc = p.upc or info.get("upc", "")
    p.mpn = p.mpn or info.get("mpn", "")
    if info.get("codigo"):
        p.specs["codigo_interno"] = info["codigo"]


def aplicar_cache(productos: list[Producto], cache: CacheDetalles) -> None:
    """Completa con lo ya guardado, sin descargar nada."""
    for p in productos:
        if p.url in cache.datos:
            _aplicar(p, cache.datos[p.url])


def enriquecer(productos: list[Producto], modulo, sesion, cache: CacheDetalles) -> int:
    """Completa upc / mpn / código interno desde la página de detalle. Devuelve descargas nuevas."""
    pendientes = [p for p in productos if p.url not in cache.datos]
    for p in productos:
        if p.url in cache.datos:
            _aplicar(p, cache.datos[p.url])
    if not pendientes:
        return 0

    local = threading.local()
    nuevos = [0]

    def descargar(p: Producto):
        if not hasattr(local, "sesion"):
            local.sesion = nueva_sesion()
        try:
            info = modulo.detalle(p, local.sesion)
        except Exception as e:  # una página caída no detiene la corrida
            log.warning("No se pudo leer el detalle de %s: %s", p.url, e)
            return
        with cache._lock:
            cache.datos[p.url] = info
            nuevos[0] += 1
            n = nuevos[0]
        _aplicar(p, info)
        if n % 50 == 0:
            cache.guardar()
            log.info("  %d de %d páginas de detalle...", n, len(pendientes))
        pausa(config.PAUSA_DETALLE_S)

    with ThreadPoolExecutor(max_workers=config.HILOS_DETALLE) as ejecutor:
        list(ejecutor.map(descargar, pendientes))
    cache.guardar()
    return nuevos[0]

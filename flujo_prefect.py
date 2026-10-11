"""Flujo para ejecutar el comparador en Prefect Cloud (a demanda, botón Run).

Prefect descarga este repositorio en cada corrida. El estado (cachés e histórico) y los reportes
viven en la rama `datos` del mismo repositorio de GitHub, porque el disco del contenedor se borra.

Requiere en Prefect Cloud dos bloques Secret:
  - "anthropic-api-key": API key de Anthropic (si falta, corre sin IA).
  - "github-token": token de GitHub con permiso Contents: Read and write sobre el repositorio.
"""
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

from prefect import flow, get_run_logger
from prefect.artifacts import create_markdown_artifact
from prefect.blocks.system import Secret

# Repositorio donde se guardan los resultados (usuario/repositorio). Puede cambiarse con GITHUB_REPO.
REPO_DATOS = os.getenv("GITHUB_REPO", "").strip() or "COMPLETAR/comparador-precios"


class _HaciaPrefect(logging.Handler):
    """Reenvía los logs del paquete `comparador` al log de la corrida en Prefect."""

    def __init__(self, logger):
        super().__init__()
        self.logger = logger

    def emit(self, record):
        self.logger.log(record.levelno, record.getMessage())


def _secreto(nombre: str) -> str:
    try:
        return Secret.load(nombre).get()
    except ValueError:  # el bloque no existe
        return ""


def _tabla(resumen: dict, enlace: str) -> str:
    filas = ["| Tienda | Exactos | Similares | Imeqmo más caro | Imeqmo más barato |",
             "|---|---|---|---|---|"]
    for tienda, d in resumen["tiendas"].items():
        if not d["disponible"]:
            filas.append(f"| {tienda} | NO DISPONIBLE | | | |")
        else:
            filas.append(f"| {tienda} | {d['exactos']} | {d['similares']} | {d['imeqmo_mas_caro']} "
                         f"| {d['imeqmo_mas_barato']} |")
    errores = "".join(f"\n- {t}: {e}" for t, e in resumen["errores"].items())
    return (f"## Comparación de precios — {resumen['alcance']}\n\n"
            f"**[Descargar el Excel]({enlace})** · {resumen['productos_imeqmo']} productos de Imeqmo · "
            f"{resumen['segundos'] // 60} min\n\n" + "\n".join(filas) +
            f"\n\n{resumen['resumen_ia']}" + (f"\n\n**Tiendas con error:**{errores}" if errores else ""))


@flow(name="comparador-precios", log_prints=True)
def comparar_precios(categorias: list[str] | None = None, usar_ia: bool = True) -> dict:
    """Compara los precios de Imeqmo con Intelaf, MacroSistemas y Click.

    categorias: inicio del nombre de las categorías de Imeqmo (p. ej. ["laptops", "monitores"]);
                vacío = todas.
    usar_ia: revisar los casos dudosos con Claude (requiere el Secret "anthropic-api-key").
    """
    logger = get_run_logger()
    log_paquete = logging.getLogger("comparador")
    log_paquete.setLevel(logging.INFO)
    puente = _HaciaPrefect(logger)
    log_paquete.addHandler(puente)
    try:
        api_key = _secreto("anthropic-api-key")
        if api_key:
            os.environ["ANTHROPIC_API_KEY"] = api_key
        elif usar_ia:
            logger.warning("No existe el Secret 'anthropic-api-key': se corre sin IA")

        from comparador.__main__ import ejecutar  # después de definir la API key
        from comparador.github_datos import GitHubDatos

        if REPO_DATOS.startswith("COMPLETAR/"):
            raise ValueError("Falta configurar REPO_DATOS en flujo_prefect.py (usuario/repositorio)")
        gh = GitHubDatos(REPO_DATOS, _secreto("github-token"))
        gh.asegurar_rama()
        salida = Path(tempfile.mkdtemp(prefix="comparador_"))
        encontrados = gh.bajar_estado(salida)
        logger.info("Estado recuperado de GitHub: %s", ", ".join(encontrados) or "ninguno (primera corrida)")

        resumen = ejecutar(categorias or [], sin_ia=not usar_ia, salida=salida)

        mensaje = f"Corrida {datetime.now():%Y-%m-%d %H:%M} ({resumen['alcance']})"
        enlace = gh.subir_reporte(resumen["ruta"], mensaje)
        gh.subir_estado(salida, mensaje)
        logger.info("Excel: %s", enlace)
        create_markdown_artifact(key="comparacion-precios", markdown=_tabla(resumen, enlace),
                                 description="Resumen de la comparación de precios")
        return {**{k: v for k, v in resumen.items() if k != "ruta"}, "excel": enlace}
    finally:
        log_paquete.removeHandler(puente)


if __name__ == "__main__":  # prueba local: python flujo_prefect.py
    comparar_precios()

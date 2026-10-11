"""Estado y reportes en una rama de GitHub (para ejecutar en Prefect Cloud, donde el disco se borra).

Usa la API REST de GitHub (no requiere git). La rama de datos se crea vacía, sin el código.

Desde la PC, para subir el estado actual una sola vez (lee GITHUB_TOKEN y GITHUB_REPO del .env):
    python -m comparador.github_datos subir-estado
"""
import argparse
import base64
import logging
import os
import sys
from pathlib import Path

import requests

API = "https://api.github.com"
RAMA = "datos"
ARCHIVOS_ESTADO = ("cache_detalles.json", "cache_ia.json", "historico.csv")
CARPETA_ESTADO = "estado"
CARPETA_REPORTES = "reportes"
README_RAMA = (
    "# Datos del comparador de precios\n\n"
    "Rama generada automáticamente por el flujo de Prefect.\n\n"
    "- `reportes/`: un Excel por corrida.\n"
    "- `estado/`: cachés (páginas de detalle, decisiones de IA) e `historico.csv`.\n"
)

log = logging.getLogger(__name__)


class GitHubDatos:
    def __init__(self, repo: str, token: str, rama: str = RAMA, sesion: requests.Session | None = None):
        if not repo or "/" not in repo:
            raise ValueError(f"Repositorio inválido: {repo!r} (formato usuario/repositorio)")
        if not token:
            raise ValueError("Falta el token de GitHub")
        self.repo, self.rama = repo, rama
        self.s = sesion or requests.Session()
        self.s.headers.update({"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28",
                               "Accept": "application/vnd.github+json"})

    def _url(self, ruta: str) -> str:
        return f"{API}/repos/{self.repo}/{ruta}"

    # ------------------------------------------------------------ rama
    def asegurar_rama(self) -> bool:
        """Crea la rama de datos (sin historia ni código) si no existe. True si la creó."""
        r = self.s.get(self._url(f"git/ref/heads/{self.rama}"), timeout=30)
        if r.status_code == 200:
            return False
        if r.status_code != 404:
            r.raise_for_status()
        arbol = self.s.post(self._url("git/trees"), timeout=30, json={
            "tree": [{"path": "README.md", "mode": "100644", "type": "blob", "content": README_RAMA}]})
        arbol.raise_for_status()
        commit = self.s.post(self._url("git/commits"), timeout=30, json={
            "message": "Crear rama de datos del comparador", "tree": arbol.json()["sha"], "parents": []})
        commit.raise_for_status()
        ref = self.s.post(self._url("git/refs"), timeout=30, json={
            "ref": f"refs/heads/{self.rama}", "sha": commit.json()["sha"]})
        ref.raise_for_status()
        log.info("GitHub: rama '%s' creada en %s", self.rama, self.repo)
        return True

    # ------------------------------------------------------------ archivos
    def descargar(self, ruta_remota: str, destino: Path) -> bool:
        """Baja un archivo de la rama de datos. False si no existe."""
        r = self.s.get(self._url(f"contents/{ruta_remota}"), params={"ref": self.rama}, timeout=60,
                       headers={"Accept": "application/vnd.github.raw+json"})  # raw: sirve para archivos > 1 MB
        if r.status_code == 404:
            return False
        r.raise_for_status()
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(r.content)
        return True

    def _sha(self, ruta_remota: str) -> str | None:
        r = self.s.get(self._url(f"contents/{ruta_remota}"), params={"ref": self.rama}, timeout=30)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json().get("sha")

    def subir(self, archivo: Path, ruta_remota: str, mensaje: str) -> str:
        """Crea o reemplaza un archivo en la rama de datos. Devuelve la URL para verlo en GitHub."""
        cuerpo = {"message": mensaje, "branch": self.rama,
                  "content": base64.b64encode(archivo.read_bytes()).decode("ascii")}
        for intento in range(2):  # un reintento si el archivo cambió entre leer el sha y escribir
            sha = self._sha(ruta_remota)
            if sha:
                cuerpo["sha"] = sha
            r = self.s.put(self._url(f"contents/{ruta_remota}"), json=cuerpo, timeout=120)
            if r.status_code in (409, 422) and intento == 0:
                continue
            r.raise_for_status()
            break
        return f"https://github.com/{self.repo}/blob/{self.rama}/{ruta_remota}"

    # ------------------------------------------------------------ estado completo
    def bajar_estado(self, carpeta: Path) -> list[str]:
        """Baja las cachés y el histórico a `carpeta`. Devuelve los nombres encontrados."""
        return [n for n in ARCHIVOS_ESTADO if self.descargar(f"{CARPETA_ESTADO}/{n}", carpeta / n)]

    def subir_estado(self, carpeta: Path, mensaje: str) -> list[str]:
        subidos = []
        for n in ARCHIVOS_ESTADO:
            if (carpeta / n).exists():
                self.subir(carpeta / n, f"{CARPETA_ESTADO}/{n}", mensaje)
                subidos.append(n)
        return subidos

    def subir_reporte(self, excel: Path, mensaje: str) -> str:
        return self.subir(excel, f"{CARPETA_REPORTES}/{excel.name}", mensaje)


def main(argv=None) -> int:
    import config  # carga el .env

    ap = argparse.ArgumentParser(prog="python -m comparador.github_datos")
    ap.add_argument("accion", choices=["subir-estado"])
    ap.add_argument("--salida", type=Path, default=Path(__file__).resolve().parent.parent / "salidas")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    gh = GitHubDatos(config.GITHUB_REPO, os.getenv("GITHUB_TOKEN", "").strip())
    gh.asegurar_rama()
    subidos = gh.subir_estado(args.salida, "Estado inicial desde la PC")
    log.info("Subidos a %s (rama %s): %s", gh.repo, gh.rama, ", ".join(subidos) or "nada")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import base64
import json
import shutil

import pytest

from comparador import github_datos
from comparador.github_datos import GitHubDatos

from conftest import FIXTURES


class _Resp:
    def __init__(self, status, data=None, content=b""):
        self.status_code, self._data, self.content = status, data, content

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _GitHubFalso:
    """Simula lo mínimo de la API de GitHub: refs, trees/commits y contents en memoria."""

    def __init__(self):
        self.headers = {}
        self.refs = {}
        self.archivos = {}  # ruta -> (bytes, sha)
        self.contador = 0

    def _sha(self):
        self.contador += 1
        return f"sha{self.contador}"

    def get(self, url, params=None, headers=None, timeout=None):
        if "/git/ref/heads/" in url:
            rama = url.rsplit("/", 1)[1]
            return _Resp(200, {"object": {"sha": self.refs[rama]}}) if rama in self.refs else _Resp(404)
        ruta = url.split("/contents/", 1)[1]
        if ruta not in self.archivos:
            return _Resp(404)
        datos, sha = self.archivos[ruta]
        if headers and "raw" in headers.get("Accept", ""):
            return _Resp(200, content=datos)
        return _Resp(200, {"sha": sha})

    def post(self, url, json=None, timeout=None):
        if url.endswith("/git/refs"):
            self.refs[json["ref"].rsplit("/", 1)[1]] = json["sha"]
        return _Resp(201, {"sha": self._sha()})

    def put(self, url, json=None, timeout=None):
        ruta = url.split("/contents/", 1)[1]
        if ruta in self.archivos and json.get("sha") != self.archivos[ruta][1]:
            return _Resp(409)
        self.archivos[ruta] = (base64.b64decode(json["content"]), self._sha())
        return _Resp(200, {})


def _gh():
    falso = _GitHubFalso()
    return GitHubDatos("usuario/comparador-precios", "token", sesion=falso), falso


def test_crea_la_rama_una_sola_vez():
    gh, falso = _gh()
    assert gh.asegurar_rama() is True and "datos" in falso.refs
    assert gh.asegurar_rama() is False


def test_subir_y_descargar_estado(tmp_path):
    gh, falso = _gh()
    origen, destino = tmp_path / "origen", tmp_path / "destino"
    origen.mkdir()
    (origen / "cache_ia.json").write_text('{"a": 1}', encoding="utf-8")
    (origen / "historico.csv").write_text("fecha\n2026", encoding="utf-8")
    assert gh.bajar_estado(destino) == []  # primera corrida: no hay nada
    assert gh.subir_estado(origen, "prueba") == ["cache_ia.json", "historico.csv"]
    assert sorted(gh.bajar_estado(destino)) == ["cache_ia.json", "historico.csv"]
    assert (destino / "historico.csv").read_text(encoding="utf-8") == "fecha\n2026"


def test_subir_reemplaza_usando_el_sha(tmp_path):
    gh, falso = _gh()
    archivo = tmp_path / "comparacion_todas_2026-10-11_0600.xlsx"
    archivo.write_bytes(b"v1")
    url = gh.subir_reporte(archivo, "v1")
    archivo.write_bytes(b"v2")
    gh.subir_reporte(archivo, "v2")
    assert falso.archivos["reportes/comparacion_todas_2026-10-11_0600.xlsx"][0] == b"v2"
    assert url == "https://github.com/usuario/comparador-precios/blob/datos/reportes/comparacion_todas_2026-10-11_0600.xlsx"


def test_valida_repo_y_token():
    with pytest.raises(ValueError):
        GitHubDatos("sin-barra", "token", sesion=_GitHubFalso())
    with pytest.raises(ValueError):
        GitHubDatos("usuario/repo", "", sesion=_GitHubFalso())


def test_ejecutar_devuelve_resumen_sin_red(tmp_path, monkeypatch, leer):
    """Corrida completa con los catálogos guardados (laptops), sin red ni IA."""
    import comparador.__main__ as principal
    from comparador.tiendas import click, imeqmo, intelaf, macrosistemas

    monkeypatch.setattr(intelaf, "obtener", lambda cfg, s: intelaf.parsear(
        json.loads(leer("intelaf.json")), "https://www.intelaf.com/precios_stock_detallado/"))
    monkeypatch.setattr(macrosistemas, "obtener", lambda cfg, s: macrosistemas.parsear(
        json.loads(leer("macrosistemas.json"))))
    monkeypatch.setattr(click, "obtener", lambda cfg, s: click.parsear(
        json.loads(leer("click.json")), "https://click.gt/products/"))
    monkeypatch.setattr(imeqmo, "obtener_todo", lambda cfg, s, filtro=None: imeqmo.parsear(
        leer("imeqmo_listado.html")))
    shutil.copy(FIXTURES / "cache_detalles.json", tmp_path / "cache_detalles.json")  # evita pedir detalles

    resumen = principal.ejecutar([], sin_ia=True, salida=tmp_path)
    assert resumen["ruta"].exists() and resumen["productos_imeqmo"] == 35
    assert set(resumen["tiendas"]) == {"Intelaf", "MacroSistemas", "Click"}
    assert resumen["tiendas"]["MacroSistemas"]["exactos"] > 0
    assert (tmp_path / "historico.csv").exists()
    assert github_datos.ARCHIVOS_ESTADO[0] == "cache_detalles.json"

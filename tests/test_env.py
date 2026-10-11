import os

from comparador.__main__ import cargar_env


def test_env_carga_la_clave(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("# comentario\nANTHROPIC_API_KEY=sk-ant-prueba\n", encoding="utf-8")
    assert cargar_env(tmp_path / ".env")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-prueba"


def test_env_vacio_no_cuenta_como_credencial(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
    cargar_env(tmp_path / ".env")
    assert "ANTHROPIC_API_KEY" not in os.environ


def test_variable_del_sistema_tiene_prioridad(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-sistema")
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=sk-ant-archivo\n", encoding="utf-8")
    cargar_env(tmp_path / ".env")
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-sistema"


def test_sin_archivo(tmp_path):
    assert cargar_env(tmp_path / ".env") is False


def test_modelo_y_esfuerzo_desde_env(monkeypatch):
    import importlib

    import pytest

    import config

    monkeypatch.setenv("IA_MODELO", "claude-haiku-4-5")
    monkeypatch.setenv("IA_EFFORT", "MEDIUM")
    importlib.reload(config)
    assert (config.IA_MODELO, config.IA_EFFORT) == ("claude-haiku-4-5", "medium")

    monkeypatch.setenv("IA_EFFORT", "rapidisimo")
    with pytest.raises(ValueError):
        importlib.reload(config)

    monkeypatch.setenv("IA_MODELO", "claude-opus-5-5")
    monkeypatch.setenv("IA_EFFORT", "low")
    importlib.reload(config)

"""Testes de robustez do JWT_SECRET (RFC 7518 §3.2 — mínimo 32 bytes)."""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import settings as settings_mod


def _reload_get_secret(tmp_path, monkeypatch, env_value=None):
    """Reaponta o arquivo de segredo para um tmp e ajusta env, retornando _get_jwt_secret."""
    monkeypatch.setattr(settings_mod, "_JWT_SECRET_FILE", tmp_path / ".jwt_secret")
    if env_value is None:
        monkeypatch.delenv("JWT_SECRET", raising=False)
    else:
        monkeypatch.setenv("JWT_SECRET", env_value)
    return settings_mod._get_jwt_secret


def test_sem_env_e_sem_arquivo_gera_forte(tmp_path, monkeypatch):
    get = _reload_get_secret(tmp_path, monkeypatch)
    secret = get()
    assert len(secret.encode()) >= 32
    # Deve ter persistido no arquivo
    assert (tmp_path / ".jwt_secret").exists()


def test_arquivo_legado_curto_e_regenerado(tmp_path, monkeypatch):
    get = _reload_get_secret(tmp_path, monkeypatch)
    # Simula arquivo legado com 30 bytes
    (tmp_path / ".jwt_secret").write_text("x" * 30)
    secret = get()
    assert len(secret.encode()) >= 32
    # O arquivo foi reescrito com o segredo forte
    assert (tmp_path / ".jwt_secret").read_text().strip() == secret


def test_arquivo_forte_e_preservado(tmp_path, monkeypatch):
    get = _reload_get_secret(tmp_path, monkeypatch)
    forte = "a" * 64
    (tmp_path / ".jwt_secret").write_text(forte)
    assert get() == forte


def test_env_curto_e_respeitado_com_aviso(tmp_path, monkeypatch):
    # Operador definiu env curto: respeitamos (não sobrescrevemos config externa)
    get = _reload_get_secret(tmp_path, monkeypatch, env_value="curto123")
    assert get() == "curto123"


def test_env_forte_usado(tmp_path, monkeypatch):
    forte = "z" * 40
    get = _reload_get_secret(tmp_path, monkeypatch, env_value=forte)
    assert get() == forte

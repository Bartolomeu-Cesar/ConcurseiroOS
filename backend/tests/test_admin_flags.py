"""
Testes de feature flags / kill switch (/api/admin/flags + enforcement).

Executar: pytest tests/test_admin_flags.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_flags.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient

from deps import get_user_id
from main import app


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)


def _override_user_id(uid):
    async def override():
        return uid
    return override


def _seed():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (1,'Admin','a@t.com','admin',?, 'admin')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (80,'Comum','c@t.com','comum',?, 'user')",
        (now,),
    )
    # Reset flags entre testes
    conn.execute("DELETE FROM app_config WHERE chave LIKE 'flag.%'")
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def test_nao_admin_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    assert client.get("/api/admin/flags").status_code == 403
    assert client.put("/api/admin/flags/ai_tutor", json={"ativo": False}).status_code == 403


def test_listar_flags_defaults():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/flags")
    assert r.status_code == 200
    flags = {f["chave"]: f["ativo"] for f in r.json()["flags"]}
    assert flags["ai_tutor"] is True
    assert flags["manutencao"] is False


def test_toggle_persiste():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/batalhas", json={"ativo": False})
    assert r.status_code == 200
    r = client.get("/api/admin/flags")
    flags = {f["chave"]: f["ativo"] for f in r.json()["flags"]}
    assert flags["batalhas"] is False
    # Público reflete
    r = client.get("/api/config/flags")
    assert r.json()["batalhas"] is False


def test_flag_desconhecida_404():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/flags/inexistente", json={"ativo": True})
    assert r.status_code == 404


def test_flag_auditada():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})
    r = client.get("/api/admin/auditoria?acao=flag")
    items = r.json()["items"]
    assert any(it["acao"] == "flag.set" for it in items)


def test_kill_switch_ai_tutor():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Desliga IA
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})
    # analisar-pdf deve responder 503
    r = client.post("/api/ai/analisar-pdf", json={"pdf_path": "x.pdf", "acao": "resumo"})
    assert r.status_code == 503


def test_config_flags_publico_reflete_ai_tutor_off():
    """O endpoint público /api/config/flags reflete ai_tutor=False quando desligada.

    É o contrato que o widget do frontend (ai-tutor-widget.js) consome para NÃO
    se injetar quando o admin desliga a flag. Independe do role do usuário.
    """
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Ligada por padrão
    r = client.get("/api/config/flags")
    assert r.status_code == 200
    assert r.json()["ai_tutor"] is True

    # Admin desliga
    client.put("/api/admin/flags/ai_tutor", json={"ativo": False})

    # Público reflete off — mesmo consultado por um usuário comum (não-admin)
    app.dependency_overrides[get_user_id] = _override_user_id(80)
    r = client.get("/api/config/flags")
    assert r.status_code == 200
    assert r.json()["ai_tutor"] is False

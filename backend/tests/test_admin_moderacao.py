"""
Testes de moderação: banir/suspender/reativar usuários e bloqueio de login.

Executar: pytest tests/test_admin_moderacao.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_mod.db", delete=False)
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
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (90,'Reu','reu@t.com','reu',?, 'user')",
        (now,),
    )
    # Reset status
    conn.execute("UPDATE users SET conta_status='ativo', conta_status_motivo='', conta_status_ate='' WHERE id=90")
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
    app.dependency_overrides[get_user_id] = _override_user_id(90)
    r = client.post("/api/admin/users/1/status", json={"status": "banido"})
    assert r.status_code == 403


def test_status_invalido():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/users/90/status", json={"status": "xpto"})
    assert r.status_code == 400


def test_nao_modera_admin_principal():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/users/1/status", json={"status": "banido"})
    assert r.status_code == 400


def test_banir_bloqueia_login():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/users/90/status", json={"status": "banido", "motivo": "spam"})
    assert r.status_code == 200

    # Login do banido deve falhar com 403
    r = client.post("/api/auth/login", json={"email": "reu@t.com"})
    assert r.status_code == 403
    assert "banida" in r.json()["detail"].lower()


def test_reativar_permite_login():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/admin/users/90/status", json={"status": "banido"})
    client.post("/api/admin/users/90/status", json={"status": "ativo"})

    r = client.post("/api/auth/login", json={"email": "reu@t.com"})
    assert r.status_code == 200


def test_suspensao_expirada_reativa_no_login():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    passado = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    client.post("/api/admin/users/90/status", json={"status": "suspenso", "ate": passado})

    # Suspensão no passado → login reativa e passa
    r = client.post("/api/auth/login", json={"email": "reu@t.com"})
    assert r.status_code == 200


def test_moderacao_auditada():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/admin/users/90/status", json={"status": "banido"})
    r = client.get("/api/admin/auditoria?acao=user.banido")
    items = r.json()["items"]
    assert any(it["acao"] == "user.banido" and str(it["alvo_id"]) == "90" for it in items)

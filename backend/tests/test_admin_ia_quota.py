"""
Testes de quota de IA por usuário (/api/admin/users/{uid}/ia-quota + enforcement).

Executar: pytest tests/test_admin_ia_quota.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_iaquota.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from deps import get_user_id
from fastapi.testclient import TestClient
from main import app
from routers import ai_tutor


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
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role, plano) VALUES (1,'Admin','a@t.com','admin',?, 'admin','free')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role, plano) VALUES (95,'Comum','c@t.com','comum',?, 'user','free')",
        (now,),
    )
    conn.execute("UPDATE users SET ai_token_limit=0 WHERE id IN (1,95)")
    conn.execute("DELETE FROM ai_usage WHERE user_id=95")
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def _db():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def test_nao_admin_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(95)
    assert client.get("/api/admin/users/95/ia-quota").status_code == 403
    assert client.put("/api/admin/users/95/ia-quota", json={"limite": -1}).status_code == 403


def test_get_quota_estrutura():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/users/95/ia-quota")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["override"] == 0
    assert len(d["timeline"]) == 7


def test_set_quota_persiste_e_audita():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.put("/api/admin/users/95/ia-quota", json={"limite": 12345})
    assert r.status_code == 200
    assert r.json()["override"] == 12345
    r = client.get("/api/admin/users/95/ia-quota")
    assert r.json()["override"] == 12345
    # auditado
    r = client.get("/api/admin/auditoria?acao=user.ia_quota")
    assert any(it["acao"] == "user.ia_quota" for it in r.json()["items"])


def test_override_ilimitado_libera_budget():
    # Free normalmente tem 50k/dia. Com override -1, _check_budget não bloqueia.
    conn = _db()
    conn.execute("UPDATE users SET ai_token_limit=-1 WHERE id=95")
    # Simula consumo enorme
    from utils import today_str
    conn.execute(
        "INSERT OR REPLACE INTO ai_usage (user_id, data, tokens_used, requests_count) VALUES (95, ?, 999999, 10)",
        (today_str(),),
    )
    conn.commit()
    info = ai_tutor._check_budget(conn, 95)
    conn.close()
    assert info["tokens_limit"] is None  # ilimitado


def test_override_custom_bloqueia_quando_excede():
    conn = _db()
    conn.execute("UPDATE users SET ai_token_limit=1000 WHERE id=95")
    from utils import today_str
    conn.execute(
        "INSERT OR REPLACE INTO ai_usage (user_id, data, tokens_used, requests_count) VALUES (95, ?, 1500, 3)",
        (today_str(),),
    )
    conn.commit()
    from fastapi import HTTPException
    raised = False
    try:
        ai_tutor._check_budget(conn, 95)
    except HTTPException as e:
        raised = True
        assert e.status_code == 429
    finally:
        conn.close()
    assert raised

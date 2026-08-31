"""
Testes do dashboard de saúde do sistema (GET /api/admin/health).

Executar: pytest tests/test_admin_health.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_health.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session
import settings as settings_mod

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
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
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (1, 'Admin', 'a@t.com', 'admin', ?, 'admin')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (50, 'Comum', 'c@t.com', 'comum', ?, 'user')",
        (now,),
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    settings_mod.settings.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def test_nao_admin_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(50)
    r = client.get("/api/admin/health")
    assert r.status_code == 403


def test_health_estrutura_completa():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/health")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "ok"
    for chave in ("bancos", "schema_version", "ia", "contagens", "backups", "ultimas_acoes"):
        assert chave in d
    # Schema aplicado (migrations rodaram)
    assert d["schema_version"] >= 69
    # Bancos reportam tamanho do progress.db
    assert "progress_db_mb" in d["bancos"]
    # Contagens incluem users (>=2 do seed)
    assert d["contagens"]["users"] >= 2
    # Timeline de IA tem 7 dias
    assert len(d["ia"]["timeline"]) == 7


def test_health_reflete_uso_de_ia():
    # Insere uso de IA de hoje e confere no health.
    from utils import today_str
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO ai_usage (user_id, data, tokens_used, requests_count) VALUES (1, ?, 1234, 5)",
        (today_str(),),
    )
    conn.commit()
    conn.close()

    app.dependency_overrides[get_user_id] = _override_user_id(1)
    d = client.get("/api/admin/health").json()
    assert d["ia"]["hoje_tokens"] >= 1234
    assert d["ia"]["hoje_requests"] >= 5

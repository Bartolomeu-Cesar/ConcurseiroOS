"""
Testes do endpoint de triggers de notificação (routers/notifications.py).
Foco: o trigger de 'plano_expirando' está integrado ao check-triggers.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_notif.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


class TestCheckTriggers:
    def test_check_triggers_inclui_plano_expirando(self, client):
        """check-triggers retorna a chave plano_expirando no resultado."""
        r = client.post("/api/push/check-triggers")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "plano_expirando" in data["notifications_sent"]

    def test_check_triggers_sem_subscriptions(self, client):
        """Sem push subscriptions, não envia nada mas responde ok."""
        r = client.post("/api/push/check-triggers")
        assert r.status_code == 200
        assert r.json()["notifications_sent"]["plano_expirando"] == 0


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

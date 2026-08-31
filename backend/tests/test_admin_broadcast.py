"""
Testes de broadcast/anúncios do admin (POST /api/admin/broadcast + feed in-app).

Executar: pytest tests/test_admin_broadcast.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_bcast.db", delete=False)
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
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role, plano) VALUES (1,'Admin','a@t.com','admin',?, 'admin','premium')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin', plano='premium' WHERE id=1")
    # Usuário free e usuário premium
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role, plano) VALUES (40,'Free','f@t.com','free',?, 'user','free')",
        (now,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role, plano) VALUES (41,'Prem','p@t.com','prem',?, 'user','premium')",
        (now,),
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def test_nao_admin_nao_envia():
    app.dependency_overrides[get_user_id] = _override_user_id(40)
    r = client.post("/api/admin/broadcast", json={"titulo": "x", "segmento": "todos"})
    assert r.status_code == 403


def test_broadcast_segmento_invalido():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "x", "segmento": "banana"})
    assert r.status_code == 400


def test_broadcast_todos_alcance():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "Manutenção", "corpo": "Amanhã 3h", "segmento": "todos"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["segmento"] == "todos"
    assert d["alcance"] >= 3  # admin + free + prem


def test_broadcast_free_nao_alcanca_premium():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/admin/broadcast", json={"titulo": "Promo Free", "segmento": "free"})

    # Usuário free vê no feed
    app.dependency_overrides[get_user_id] = _override_user_id(40)
    r = client.get("/api/broadcasts/feed")
    assert r.status_code == 200
    titulos = [a["titulo"] for a in r.json()["anuncios"]]
    assert "Promo Free" in titulos

    # Usuário premium NÃO vê a promo free
    app.dependency_overrides[get_user_id] = _override_user_id(41)
    r = client.get("/api/broadcasts/feed")
    titulos = [a["titulo"] for a in r.json()["anuncios"]]
    assert "Promo Free" not in titulos


def test_dispensar_remove_do_feed():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "Aviso Geral", "segmento": "todos"})
    bid = r.json()["id"]

    app.dependency_overrides[get_user_id] = _override_user_id(41)
    r = client.get("/api/broadcasts/feed")
    assert any(a["id"] == bid for a in r.json()["anuncios"])

    # Dispensa
    r = client.post(f"/api/broadcasts/{bid}/dispensar")
    assert r.status_code == 200

    r = client.get("/api/broadcasts/feed")
    assert not any(a["id"] == bid for a in r.json()["anuncios"])


def test_historico_broadcasts():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/admin/broadcast", json={"titulo": "Hist1", "segmento": "todos"})
    r = client.get("/api/admin/broadcasts")
    assert r.status_code == 200
    data = r.json()
    items = data["items"] if isinstance(data, dict) else data
    assert any(it["titulo"] == "Hist1" for it in items)


def test_broadcast_auditado():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/admin/broadcast", json={"titulo": "Auditado", "segmento": "todos"})
    r = client.get("/api/admin/auditoria?acao=broadcast")
    items = r.json()["items"]
    assert any(it["acao"] == "broadcast.enviar" for it in items)

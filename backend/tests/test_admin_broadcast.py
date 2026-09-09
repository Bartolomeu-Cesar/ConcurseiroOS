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

from deps import get_user_id
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


def _get_expira_em(bid):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    row = conn.execute("SELECT expira_em FROM broadcasts WHERE id = ?", (bid,)).fetchone()
    conn.close()
    return row[0] if row else None


def test_broadcast_default_7_dias():
    """Sem informar validade, expira_em ~ agora + 7 dias."""
    from datetime import datetime, timedelta, timezone
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "Default7", "segmento": "todos"})
    bid = r.json()["id"]
    expira = _get_expira_em(bid)
    assert expira  # não vazio
    dt = datetime.fromisoformat(expira)
    esperado = datetime.now(timezone.utc) + timedelta(days=7)
    # tolerância de 1 dia
    assert abs((dt - esperado).total_seconds()) < 86400


def test_broadcast_dias_validade_customizado():
    from datetime import datetime, timedelta, timezone
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "Val3", "segmento": "todos", "dias_validade": 3})
    bid = r.json()["id"]
    dt = datetime.fromisoformat(_get_expira_em(bid))
    esperado = datetime.now(timezone.utc) + timedelta(days=3)
    assert abs((dt - esperado).total_seconds()) < 86400


def test_broadcast_expira_em_explicito():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "DataFixa", "segmento": "todos", "expira_em": "2030-12-31"})
    assert r.status_code == 200
    expira = _get_expira_em(r.json()["id"])
    assert expira.startswith("2030-12-31")


def test_broadcast_expira_em_invalido_400():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "Ruim", "segmento": "todos", "expira_em": "31/12/2030"})
    assert r.status_code == 400


def test_broadcast_expirado_some_do_feed():
    """Anúncio com expira_em no passado não aparece no feed."""
    from datetime import datetime, timedelta, timezone
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "JaExpirou", "segmento": "todos"})
    bid = r.json()["id"]
    # Forçar expiração no passado
    passado = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("UPDATE broadcasts SET expira_em = ? WHERE id = ?", (passado, bid))
    conn.commit()
    conn.close()

    app.dependency_overrides[get_user_id] = _override_user_id(41)
    r = client.get("/api/broadcasts/feed")
    assert not any(a["id"] == bid for a in r.json()["anuncios"])


def test_broadcast_sem_expira_em_aparece_no_feed():
    """Retrocompat: anúncio com expira_em vazio continua aparecendo."""
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.post("/api/admin/broadcast", json={"titulo": "SemExpira", "segmento": "todos"})
    bid = r.json()["id"]
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("UPDATE broadcasts SET expira_em = '' WHERE id = ?", (bid,))
    conn.commit()
    conn.close()

    app.dependency_overrides[get_user_id] = _override_user_id(41)
    r = client.get("/api/broadcasts/feed")
    assert any(a["id"] == bid for a in r.json()["anuncios"])


def test_historico_inclui_expira_em():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/admin/broadcast", json={"titulo": "HistExp", "segmento": "todos", "dias_validade": 5})
    r = client.get("/api/admin/broadcasts")
    items = r.json()["items"]
    alvo = next(it for it in items if it["titulo"] == "HistExp")
    assert alvo.get("expira_em")

"""
Testes do log de auditoria de ações do admin (admin_audit + GET /api/admin/auditoria).

Usa override de get_user_id (AUTH_ENABLED=false) para simular admin vs usuário comum.

Executar: pytest tests/test_admin_audit.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_audit.db", delete=False)
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
    # Admin (1) e um usuário comum (50) + alvo (60)
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
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (60, 'Alvo', 'alvo@t.com', 'alvo', ?, 'user')",
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


def test_nao_admin_nao_acessa_auditoria():
    app.dependency_overrides[get_user_id] = _override_user_id(50)
    r = client.get("/api/admin/auditoria")
    assert r.status_code == 403


def test_auditoria_registra_alteracao_de_plano():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Ação que deve gerar log
    r = client.post("/api/admin/users/60/plano", json={"plano": "premium", "plano_expira": ""})
    assert r.status_code == 200, r.text

    # Consulta o log
    r = client.get("/api/admin/auditoria")
    assert r.status_code == 200
    data = r.json()
    items = data["items"] if isinstance(data, dict) else data
    acoes = [it["acao"] for it in items]
    assert "user.plano" in acoes
    # A linha deve conter o admin que executou e o alvo
    linha = next(it for it in items if it["acao"] == "user.plano")
    assert linha["admin_id"] == 1
    assert str(linha["alvo_id"]) == "60"


def test_auditoria_registra_creditos_e_filtra_por_acao():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/admin/users/60/creditos", json={"quantidade": 10, "motivo": "teste"})

    r = client.get("/api/admin/auditoria?acao=user.creditos")
    assert r.status_code == 200
    data = r.json()
    items = data["items"] if isinstance(data, dict) else data
    assert len(items) >= 1
    assert all(it["acao"].startswith("user.creditos") for it in items)


def test_auditoria_registra_exclusao_de_usuario():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Cria e exclui um usuário — ambos devem ser auditados
    r = client.post("/api/admin/users", json={
        "email": "descartavel@t.com", "nome": "Descartavel", "username": "desc", "plano": "free", "password": ""
    })
    assert r.status_code == 200, r.text
    novo_id = r.json()["id"]

    r = client.delete(f"/api/admin/users/{novo_id}")
    assert r.status_code == 200, r.text

    r = client.get("/api/admin/auditoria")
    items = r.json()["items"]
    acoes = [it["acao"] for it in items]
    assert "user.create" in acoes
    assert "user.delete" in acoes


def test_auditoria_paginacao():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Gera várias ações
    for _ in range(3):
        client.post("/api/admin/users/60/creditos", json={"quantidade": 1, "motivo": "p"})
    r = client.get("/api/admin/auditoria?page=1&limit=2")
    assert r.status_code == 200
    data = r.json()
    assert data["limit"] == 2
    assert len(data["items"]) <= 2
    assert data["total"] >= 3

"""
Testes para o status de presença social (routers/social/status.py).
Cobre: atualizar status (heartbeat), listar status de amigos (online/offline),
resumo motivacional e privacidade (só amigos aparecem).

AUTH_ENABLED=false → user_id sempre 1 (single-user), então testamos a
perspectiva do user 1 vendo seus amigos.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_social_status.db", delete=False)
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


def _conn():
    c = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _criar_usuarios_e_amizade():
    """Cria users 1 (eu), 2 (amigo), 3 (não-amigo) e amizade 1↔2."""
    conn = _conn()
    for uid, nome in [(1, "Eu"), (2, "Amigo"), (3, "Estranho")]:
        conn.execute("""
            INSERT OR IGNORE INTO users (id, nome, username, email, password_hash, plano, created_at)
            VALUES (?, ?, ?, ?, 'hash', 'free', '2026-01-01')
        """, (uid, nome, f"user{uid}", f"user{uid}@test.com"))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS friendships (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user_a INTEGER, user_b INTEGER,
            status TEXT DEFAULT 'pending', created_at TEXT
        )
    """)
    existing = conn.execute("SELECT id FROM friendships WHERE user_a=1 AND user_b=2").fetchone()
    if not existing:
        conn.execute("INSERT INTO friendships (user_a, user_b, status, created_at) VALUES (1, 2, 'accepted', '2026-01-01')")
    conn.commit()
    conn.close()


def _set_status_direto(user_id, status, atualizado_em, materia=""):
    """Insere status direto no banco com timestamp controlado."""
    conn = _conn()
    conn.execute("""
        INSERT INTO user_status (user_id, status, materia, detalhe, atualizado_em)
        VALUES (?, ?, ?, '', ?)
        ON CONFLICT(user_id) DO UPDATE SET status=excluded.status, materia=excluded.materia, atualizado_em=excluded.atualizado_em
    """, (user_id, status, materia, atualizado_em))
    conn.commit()
    conn.close()


class TestAtualizarStatus:
    def test_atualizar_status_ok(self, client):
        r = client.post("/api/social/status", json={"status": "estudando", "materia": "Direito"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["status"] == "estudando"

    def test_status_invalido_vira_estudando(self, client):
        r = client.post("/api/social/status", json={"status": "xpto"})
        assert r.status_code == 200
        assert r.json()["status"] == "estudando"

    def test_marcar_offline(self, client):
        client.post("/api/social/status", json={"status": "focado"})
        r = client.post("/api/social/status/offline")
        assert r.status_code == 200
        assert r.json()["ok"] is True


class TestStatusAmigos:
    def test_amigo_online_aparece(self, client):
        _criar_usuarios_e_amizade()
        agora = datetime.now(timezone.utc).isoformat()
        _set_status_direto(2, "estudando", agora, materia="Português")
        r = client.get("/api/social/status/amigos")
        assert r.status_code == 200
        data = r.json()
        amigo = next((a for a in data["amigos"] if a["user_id"] == 2), None)
        assert amigo is not None
        assert amigo["online"] is True
        assert amigo["status"] == "estudando"
        assert amigo["materia"] == "Português"
        assert data["online_count"] >= 1

    def test_amigo_offline_por_tempo(self, client):
        _criar_usuarios_e_amizade()
        antigo = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
        _set_status_direto(2, "estudando", antigo)
        r = client.get("/api/social/status/amigos")
        data = r.json()
        amigo = next((a for a in data["amigos"] if a["user_id"] == 2), None)
        assert amigo is not None
        assert amigo["online"] is False
        # Matéria não é exposta se offline
        assert amigo["materia"] == ""

    def test_nao_amigo_nao_aparece(self, client):
        _criar_usuarios_e_amizade()
        agora = datetime.now(timezone.utc).isoformat()
        _set_status_direto(3, "estudando", agora)  # user 3 não é amigo
        r = client.get("/api/social/status/amigos")
        data = r.json()
        ids = [a["user_id"] for a in data["amigos"]]
        assert 3 not in ids

    def test_sem_amigos_lista_vazia(self, client):
        # Remover amizades para simular sem amigos
        conn = _conn()
        conn.execute("DELETE FROM friendships")
        conn.commit()
        conn.close()
        r = client.get("/api/social/status/amigos")
        assert r.status_code == 200
        assert r.json()["amigos"] == []


class TestResumo:
    def test_resumo_com_amigos_estudando(self, client):
        _criar_usuarios_e_amizade()
        agora = datetime.now(timezone.utc).isoformat()
        _set_status_direto(2, "focado", agora)
        r = client.get("/api/social/status/resumo")
        assert r.status_code == 200
        data = r.json()
        assert "mensagem" in data
        assert data["estudando_count"] >= 1

    def test_resumo_sem_ninguem(self, client):
        conn = _conn()
        conn.execute("DELETE FROM friendships")
        conn.commit()
        conn.close()
        r = client.get("/api/social/status/resumo")
        assert r.status_code == 200
        data = r.json()
        assert "mensagem" in data
        assert data["estudando_count"] == 0


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

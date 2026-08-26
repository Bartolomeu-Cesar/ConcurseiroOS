"""
Testes para o chat direto entre amigos (Social router).
Cobre: envio de mensagem, listagem de conversas, contagem de não lidas, leitura.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_social_chat.db", delete=False)
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


def _setup_friendship(accepted=True):
    """Create two test users and a friendship between them."""
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # Create users if not exist
    conn.execute("""
        INSERT OR IGNORE INTO users (id, nome, username, email, password_hash, plano, created_at)
        VALUES (1, 'User One', 'user1', 'user1@test.com', 'hash', 'free', '2026-01-01')
    """)
    conn.execute("""
        INSERT OR IGNORE INTO users (id, nome, username, email, password_hash, plano, created_at)
        VALUES (2, 'User Two', 'user2', 'user2@test.com', 'hash', 'free', '2026-01-01')
    """)

    # Create friendships table if not exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS friendships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_a INTEGER NOT NULL,
            user_b INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    # Create friendship
    status = 'accepted' if accepted else 'pending'
    existing = conn.execute(
        "SELECT id FROM friendships WHERE user_a = 1 AND user_b = 2"
    ).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO friendships (user_a, user_b, status, created_at) VALUES (1, 2, ?, '2026-01-01')",
            (status,)
        )
    else:
        conn.execute("UPDATE friendships SET status = ? WHERE user_a = 1 AND user_b = 2", (status,))

    conn.commit()
    conn.close()


class TestSendMessage:
    """Testes para POST /api/social/chat/send"""

    def test_send_message_success(self, client):
        """Enviar mensagem para amigo aceito deve funcionar."""
        _setup_friendship(accepted=True)
        resp = client.post("/api/social/chat/send", json={
            "receiver_id": 2,
            "mensagem": "Olá, vamos estudar juntos!"
        })
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert data["ok"] is True
        assert "created_at" in data

    def test_send_message_empty(self, client):
        """Mensagem vazia deve ser rejeitada."""
        _setup_friendship(accepted=True)
        resp = client.post("/api/social/chat/send", json={
            "receiver_id": 2,
            "mensagem": ""
        })
        assert resp.status_code == 400

    def test_send_message_too_long(self, client):
        """Mensagem muito longa deve ser rejeitada."""
        _setup_friendship(accepted=True)
        resp = client.post("/api/social/chat/send", json={
            "receiver_id": 2,
            "mensagem": "x" * 1001
        })
        assert resp.status_code == 400

    def test_send_message_to_self(self, client):
        """Não pode enviar mensagem para si mesmo."""
        resp = client.post("/api/social/chat/send", json={
            "receiver_id": 1,
            "mensagem": "Olá eu mesmo"
        })
        assert resp.status_code == 400

    def test_send_message_not_friends(self, client):
        """Não pode enviar mensagem para quem não é amigo."""
        _setup_friendship(accepted=False)
        # User 3 não existe como amigo
        conn = sqlite3.connect(_tmp_db.name, check_same_thread=False)
        conn.execute("""
            INSERT OR IGNORE INTO users (id, nome, username, email, password_hash, plano, created_at)
            VALUES (3, 'User Three', 'user3', 'user3@test.com', 'hash', 'free', '2026-01-01')
        """)
        conn.commit()
        conn.close()

        resp = client.post("/api/social/chat/send", json={
            "receiver_id": 3,
            "mensagem": "Oi"
        })
        assert resp.status_code == 403


class TestConversations:
    """Testes para GET /api/social/chat/conversations e /chat/{friend_id}"""

    def test_list_conversations(self, client):
        """Deve listar conversas ativas."""
        _setup_friendship(accepted=True)
        # Send a message first
        client.post("/api/social/chat/send", json={
            "receiver_id": 2,
            "mensagem": "Msg para teste de conversas"
        })
        resp = client.get("/api/social/chat/conversations")
        assert resp.status_code == 200
        data = resp.json()
        assert "conversations" in data
        assert "total_unread" in data

    def test_get_messages(self, client):
        """Deve retornar mensagens entre dois amigos."""
        _setup_friendship(accepted=True)
        client.post("/api/social/chat/send", json={
            "receiver_id": 2,
            "mensagem": "Primeira mensagem"
        })
        resp = client.get("/api/social/chat/2")
        assert resp.status_code == 200
        data = resp.json()
        assert "messages" in data
        assert len(data["messages"]) >= 1
        assert data["messages"][-1]["mensagem"] == "Primeira mensagem"

    def test_get_messages_not_friends(self, client):
        """Não pode ler mensagens de quem não é amigo."""
        # User 3 sem amizade com user 1
        resp = client.get("/api/social/chat/3")
        assert resp.status_code == 403


class TestUnreadCount:
    """Testes para GET /api/social/chat/unread/count"""

    def test_unread_count(self, client):
        """Deve retornar contagem de não lidas."""
        resp = client.get("/api/social/chat/unread/count")
        assert resp.status_code == 200
        data = resp.json()
        assert "unread" in data
        assert isinstance(data["unread"], int)


class TestPendingFriends:
    """Testes para GET /api/social/friends/pending"""

    def test_pending_requests(self, client):
        """Deve listar pedidos pendentes (enviados + recebidos)."""
        resp = client.get("/api/social/friends/pending")
        assert resp.status_code == 200
        data = resp.json()
        assert "pending" in data
        assert "sent" in data

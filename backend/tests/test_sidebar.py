"""
Testes do endpoint consolidado /api/sidebar-data.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_sidebar.db", delete=False)
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


class TestSidebarData:
    """Testes do endpoint /api/sidebar-data."""

    def test_returns_200(self, client):
        r = client.get("/api/sidebar-data")
        assert r.status_code == 200

    def test_response_structure(self, client):
        r = client.get("/api/sidebar-data")
        data = r.json()
        assert "streak" in data
        assert "nivel" in data
        assert "xp" in data
        assert "freezes_available" in data
        assert "badges" in data
        assert "sugestao" in data

    def test_badges_structure(self, client):
        r = client.get("/api/sidebar-data")
        badges = r.json()["badges"]
        assert "flashcards" in badges
        assert "sumulas" in badges
        assert "caderno" in badges
        assert isinstance(badges["flashcards"], int)
        assert isinstance(badges["sumulas"], int)
        assert isinstance(badges["caderno"], int)

    def test_streak_is_integer(self, client):
        r = client.get("/api/sidebar-data")
        data = r.json()
        assert isinstance(data["streak"], int)
        assert isinstance(data["nivel"], int)
        assert isinstance(data["xp"], int)
        assert data["nivel"] >= 1

    def test_freezes_default(self, client):
        r = client.get("/api/sidebar-data")
        data = r.json()
        assert isinstance(data["freezes_available"], int)
        assert data["freezes_available"] >= 0

    def test_sugestao_structure(self, client):
        r = client.get("/api/sidebar-data")
        sugestao = r.json()["sugestao"]
        assert isinstance(sugestao, dict)

    def test_badges_reflect_pending_flashcards(self, client):
        """Flashcards pendentes devem aparecer no badge count."""
        r = client.post("/api/flashcards", json={
            "pergunta": "Teste sidebar?",
            "resposta": "Resposta teste",
            "materia": "Direito"
        })
        assert r.status_code == 200

        r = client.get("/api/sidebar-data")
        data = r.json()
        assert data["badges"]["flashcards"] >= 1

    def test_badges_reflect_pending_sumulas(self, client):
        """Súmulas pendentes devem aparecer no badge count."""
        r = client.post("/api/sumulas", json={
            "numero": 123,
            "tribunal": "STF",
            "enunciado": "Texto teste",
            "tema": "Tema"
        })
        assert r.status_code == 200

        r = client.get("/api/sidebar-data")
        data = r.json()
        assert data["badges"]["sumulas"] >= 1

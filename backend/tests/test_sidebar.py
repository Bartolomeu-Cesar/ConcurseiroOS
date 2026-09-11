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

    def test_badge_caderno_respeita_ciclo_ativo(self, client):
        """O badge do caderno de erros NÃO deve contar questões pendentes de
        matérias FORA do ciclo ativo (regra nº 2). Antes, o sidebar contava
        todas as linhas de erros_revisao e divergia do que a página mostra."""
        from utils import today_str

        # Cria questões via API (garante colunas obrigatórias/created_at)
        def _cria(materia):
            r = client.post("/api/questoes", json={
                "materia": materia, "topico": "T", "enunciado": "E?",
                "alternativa_a": "A", "alternativa_b": "B", "alternativa_c": "C",
                "alternativa_d": "D", "alternativa_e": "", "resposta_correta": "A",
                "explicacao": "x", "dificuldade": "Médio",
            })
            assert r.status_code == 200
            return r.json()["id"]

        conn = sqlite3.connect(_tmp_db.name, timeout=10)
        conn.row_factory = sqlite3.Row
        for t in ("erros_revisao", "ciclo_estudos"):
            try:
                conn.execute(f"DELETE FROM {t} WHERE 1=1")
            except Exception:
                pass
        conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Informática', 1, 1)")
        conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Direito Constitucional', 0, 1)")
        conn.commit()
        conn.close()

        q_ativa = _cria("Informática")
        q_inativa = _cria("Direito Constitucional")

        conn = sqlite3.connect(_tmp_db.name, timeout=10)
        conn.row_factory = sqlite3.Row
        for qid in (q_ativa, q_inativa):
            conn.execute(
                "INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, "
                "proxima_revisao, revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review) "
                "VALUES (1, ?, 0, 1, ?, 0, ?, 0, 0, 0, 0, NULL)",
                (qid, today_str(), today_str()),
            )
        conn.commit()
        conn.close()

        data = client.get("/api/sidebar-data").json()
        # Só a questão do ciclo ativo conta → badge = 1 (não 2)
        assert data["badges"]["caderno"] == 1, \
            "badge do caderno deve contar apenas matérias do ciclo ativo"

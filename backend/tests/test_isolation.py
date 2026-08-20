"""
Testes de isolamento multi-usuário.
Verifica que dados de user_id=1 não aparecem para user_id=2 e vice-versa.

Executar: pytest tests/test_isolation.py -v
"""
import os
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import settings as settings_mod

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
database.init_db()

from unittest.mock import patch

from fastapi.testclient import TestClient

from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _override_user_id(uid):
    """Helper to override user_id dependency for testing."""
    async def override():
        return uid
    return override


from deps import get_user_id


class TestIsolationEdital:
    """Testa que editais de um usuário não aparecem para outro."""

    def test_user1_creates_edital(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.post("/api/edital", json={
            "materia": "Direito Penal",
            "topico": "Tópico User 1",
            "edital_nome": "Concurso User1",
            "cargo": "Delegado"
        })
        assert r.status_code == 200
        assert r.json()["materia"] == "Direito Penal"

    def test_user2_creates_edital(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.post("/api/edital", json={
            "materia": "Direito Civil",
            "topico": "Tópico User 2",
            "edital_nome": "Concurso User2",
            "cargo": "Juiz"
        })
        assert r.status_code == 200
        assert r.json()["materia"] == "Direito Civil"

    def test_user1_only_sees_own_edital(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.get("/api/edital")
        assert r.status_code == 200
        data = r.json()
        materias = [d["materia"] for d in data]
        assert "Direito Penal" in materias
        assert "Direito Civil" not in materias

    def test_user2_only_sees_own_edital(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.get("/api/edital")
        assert r.status_code == 200
        data = r.json()
        materias = [d["materia"] for d in data]
        assert "Direito Civil" in materias
        assert "Direito Penal" not in materias


class TestIsolationFlashcards:
    """Testa que flashcards de um usuário não aparecem para outro."""

    def test_user1_creates_flashcard(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.post("/api/flashcards", json={
            "pergunta": "Pergunta User1",
            "resposta": "Resposta User1"
        })
        assert r.status_code == 200

    def test_user2_creates_flashcard(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.post("/api/flashcards", json={
            "pergunta": "Pergunta User2",
            "resposta": "Resposta User2"
        })
        assert r.status_code == 200

    def test_user1_only_sees_own_flashcards(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.get("/api/flashcards")
        assert r.status_code == 200
        perguntas = [f["pergunta"] for f in r.json()]
        assert "Pergunta User1" in perguntas
        assert "Pergunta User2" not in perguntas

    def test_user2_only_sees_own_flashcards(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.get("/api/flashcards")
        assert r.status_code == 200
        perguntas = [f["pergunta"] for f in r.json()]
        assert "Pergunta User2" in perguntas
        assert "Pergunta User1" not in perguntas


class TestIsolationQuestoes:
    """Testa que questões e respostas são isoladas por usuário."""

    def test_user1_creates_questao(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.post("/api/questoes", json={
            "materia": "Mat User1",
            "enunciado": "Questão User1?",
            "alternativa_a": "A", "alternativa_b": "B",
            "alternativa_c": "C", "alternativa_d": "D",
            "resposta_correta": "A"
        })
        assert r.status_code == 200

    def test_user2_creates_questao(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.post("/api/questoes", json={
            "materia": "Mat User2",
            "enunciado": "Questão User2?",
            "alternativa_a": "A", "alternativa_b": "B",
            "alternativa_c": "C", "alternativa_d": "D",
            "resposta_correta": "B"
        })
        assert r.status_code == 200

    def test_user1_only_sees_own_questoes(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.get("/api/questoes")
        assert r.status_code == 200
        enunciados = [q["enunciado"] for q in r.json()]
        assert "Questão User1?" in enunciados
        assert "Questão User2?" not in enunciados

    def test_user2_only_sees_own_questoes(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.get("/api/questoes")
        assert r.status_code == 200
        enunciados = [q["enunciado"] for q in r.json()]
        assert "Questão User2?" in enunciados
        assert "Questão User1?" not in enunciados


class TestIsolationMetas:
    """Testa que metas são isoladas por usuário."""

    def test_user1_updates_metas(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.put("/api/metas", json={
            "meta_horas": 5.0,
            "meta_questoes": 100,
            "meta_flashcards": 20,
            "meta_paginas": 50,
            "meta_sumulas": 5
        })
        assert r.status_code == 200

    def test_user2_updates_metas(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.put("/api/metas", json={
            "meta_horas": 2.0,
            "meta_questoes": 20,
            "meta_flashcards": 5,
            "meta_paginas": 10,
            "meta_sumulas": 0
        })
        assert r.status_code == 200

    def test_user1_sees_own_metas(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.get("/api/metas")
        assert r.status_code == 200
        config = r.json()["config"]
        assert config["meta_horas"] == 5.0
        assert config["meta_sumulas"] == 5

    def test_user2_sees_own_metas(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.get("/api/metas")
        assert r.status_code == 200
        config = r.json()["config"]
        assert config["meta_horas"] == 2.0
        assert config["meta_sumulas"] == 0


class TestIsolationDashboard:
    """Testa que o dashboard mostra apenas dados do usuário."""

    def test_user1_dashboard_isolated(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        # User1 tem 1 edital criado
        assert r.json()["edital"]["total"] >= 1

    def test_user2_dashboard_isolated(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        # User2 tem apenas seu edital
        assert r.json()["edital"]["total"] == 1


class TestIsolationSumulas:
    """Testa que súmulas são isoladas por usuário."""

    def test_user1_creates_sumula(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.post("/api/sumulas", json={
            "tribunal": "STF",
            "numero": 11,
            "enunciado": "Súmula STF 11 - User1"
        })
        assert r.status_code == 200

    def test_user2_creates_sumula(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(2)
        r = client.post("/api/sumulas", json={
            "tribunal": "STJ",
            "numero": 7,
            "enunciado": "Súmula STJ 7 - User2"
        })
        assert r.status_code == 200

    def test_user1_only_sees_own_sumulas(self, client):
        app.dependency_overrides[get_user_id] = _override_user_id(1)
        r = client.get("/api/sumulas")
        assert r.status_code == 200
        enunciados = [s["enunciado"] for s in r.json()]
        assert "Súmula STF 11 - User1" in enunciados
        assert "Súmula STJ 7 - User2" not in enunciados


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    app.dependency_overrides.clear()
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

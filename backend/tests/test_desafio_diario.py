"""
Testes de integração do Desafio Diário.
Cobre geração de desafio, idempotência, submissão de respostas, e DB vazio.

Executar: pytest tests/test_desafio_diario.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_desafio_diario.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

# Ajustar path para imports
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
    """TestClient compartilhado por todo o módulo de testes."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


@pytest.fixture(scope="module")
def setup_questoes(client):
    """Cria questões no banco para serem usadas nos desafios."""
    questoes_ids = []
    for i in range(10):
        dificuldade = "Fácil" if i < 3 else ("Médio" if i < 7 else "Difícil")
        r = client.post("/api/questoes", json={
            "materia": "Direito Constitucional",
            "topico": "Princípios Fundamentais",
            "enunciado": f"Questão desafio #{i + 1}: O que estabelece o art. {i + 1}?",
            "alternativa_a": "Alternativa A",
            "alternativa_b": "Alternativa B",
            "alternativa_c": "Alternativa C",
            "alternativa_d": "Alternativa D",
            "alternativa_e": "",
            "resposta_correta": "A",
            "explicacao": f"Explicação da questão {i + 1}",
            "dificuldade": dificuldade,
        })
        assert r.status_code == 200
        data = r.json()
        questoes_ids.append(data.get("id", i + 1))
    return questoes_ids


# ============================================================
# GET /api/desafio-diario — Sem questões no banco (DB vazio)
# ============================================================

class TestDesafioDiarioVazio:
    def test_desafio_diario_sem_questoes(self, client):
        """Quando não há questões no banco, retorna graciosamente."""
        r = client.get("/api/desafio-diario")
        assert r.status_code == 200
        data = r.json()
        # Deve retornar lista vazia de questões e mensagem informativa
        assert data["questoes"] == []
        assert data["id"] is None
        assert "message" in data


# ============================================================
# GET /api/desafio-diario — Com questões no banco
# ============================================================

class TestDesafioDiarioGerar:
    def test_gerar_desafio_diario_retorna_5_questoes(self, client, setup_questoes):
        """GET /api/desafio-diario retorna 5 questões quando há questões no banco."""
        r = client.get("/api/desafio-diario")
        assert r.status_code == 200
        data = r.json()
        assert data["id"] is not None
        assert len(data["questoes"]) == 5
        assert data["completado"] is False
        assert data["pontos_possiveis"] > 0
        # Verificar estrutura de cada questão
        for q in data["questoes"]:
            assert "id" in q
            assert "materia" in q
            assert "enunciado" in q
            assert "alternativas" in q
            assert len(q["alternativas"]) >= 4

    def test_desafio_diario_idempotente(self, client, setup_questoes):
        """Chamar GET /api/desafio-diario duas vezes no mesmo dia retorna o mesmo set."""
        r1 = client.get("/api/desafio-diario")
        assert r1.status_code == 200
        data1 = r1.json()

        r2 = client.get("/api/desafio-diario")
        assert r2.status_code == 200
        data2 = r2.json()

        # Mesmo ID de desafio
        assert data1["id"] == data2["id"]
        # Mesmas questões na mesma ordem
        ids1 = [q["id"] for q in data1["questoes"]]
        ids2 = [q["id"] for q in data2["questoes"]]
        assert ids1 == ids2


# ============================================================
# POST /api/desafio-diario/responder — Submeter respostas
# ============================================================

class TestDesafioDiarioResponder:
    def test_submeter_respostas_com_score(self, client, setup_questoes):
        """Submete respostas e recebe pontuação."""
        # Primeiro gerar o desafio (pode já existir do teste anterior)
        r = client.get("/api/desafio-diario")
        assert r.status_code == 200
        data = r.json()

        # Se já foi completado (de um teste anterior), limpar
        if data["completado"]:
            # Resetar o desafio para permitir nova submissão
            conn = sqlite3.connect(_tmp_db.name)
            conn.execute("UPDATE desafio_diario SET completado = 0 WHERE user_id = 1")
            conn.commit()
            conn.close()

        questoes = data["questoes"]
        assert len(questoes) > 0

        # Construir respostas (todas "A" = corretas pois criamos com resposta_correta = "A")
        respostas = [
            {"questao_id": q["id"], "resposta": "A"}
            for q in questoes
        ]

        r = client.post("/api/desafio-diario/responder", json={"respostas": respostas})
        assert r.status_code == 200
        result = r.json()
        assert "acertos" in result
        assert "total" in result
        assert "pontos_ganhos" in result
        assert "resultados" in result
        assert result["total"] == len(questoes)
        # Todas corretas
        assert result["acertos"] == len(questoes)
        assert result["pontos_ganhos"] > 0

    def test_submeter_respostas_parciais(self, client, setup_questoes):
        """Submete mix de respostas corretas e erradas."""
        # Limpar desafio anterior e recriar
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM desafio_diario WHERE user_id = 1")
        conn.commit()
        conn.close()

        r = client.get("/api/desafio-diario")
        assert r.status_code == 200
        questoes = r.json()["questoes"]

        # Metade correta (A), metade errada (B)
        respostas = []
        for i, q in enumerate(questoes):
            respostas.append({
                "questao_id": q["id"],
                "resposta": "A" if i % 2 == 0 else "B",
            })

        r = client.post("/api/desafio-diario/responder", json={"respostas": respostas})
        assert r.status_code == 200
        result = r.json()
        assert result["acertos"] < result["total"]
        assert result["acertos"] >= 1

    def test_submeter_desafio_ja_completado(self, client, setup_questoes):
        """Não permite submeter duas vezes no mesmo dia."""
        # O desafio anterior já foi completado
        r = client.get("/api/desafio-diario")
        data = r.json()

        if not data["completado"]:
            # Completar primeiro
            respostas = [{"questao_id": q["id"], "resposta": "A"} for q in data["questoes"]]
            client.post("/api/desafio-diario/responder", json={"respostas": respostas})

        # Tentar submeter novamente
        respostas = [{"questao_id": q["id"], "resposta": "A"} for q in data["questoes"]]
        r = client.post("/api/desafio-diario/responder", json={"respostas": respostas})
        assert r.status_code == 400
        assert "já foi completado" in r.json()["detail"]

    def test_submeter_sem_desafio_gerado(self, client, setup_questoes):
        """Retorna 404 se tentar responder sem ter desafio gerado."""
        # Limpar todos os desafios
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM desafio_diario WHERE user_id = 1")
        conn.commit()
        conn.close()

        r = client.post("/api/desafio-diario/responder", json={
            "respostas": [{"questao_id": 1, "resposta": "A"}]
        })
        assert r.status_code == 404


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

"""
Testes do endpoint /api/questoes/erros/analise — Error Analysis.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_error_analysis.db", delete=False)
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


def _create_questao_and_resposta(client):
    """Helper: cria uma questão e registra uma resposta errada, retorna resposta_id."""
    # Criar questão
    r = client.post("/api/questoes", json={
        "materia": "Direito Constitucional",
        "topico": "Princípios Fundamentais",
        "enunciado": "Qual é o fundamento da República Federativa do Brasil?",
        "alternativa_a": "Soberania",
        "alternativa_b": "Cidadania",
        "alternativa_c": "Dignidade da pessoa humana",
        "alternativa_d": "Todos os anteriores",
        "alternativa_e": "",
        "resposta_correta": "D",
        "explicacao": "Art. 1º da CF/88",
        "dificuldade": "Fácil"
    })
    assert r.status_code == 200
    questao_id = r.json()["id"]

    # Responder errado para poder analisar o erro
    r = client.post(f"/api/questoes/{questao_id}/responder", json={
        "resposta": "A",
        "tempo_segundos": 30
    })
    assert r.status_code == 200
    assert r.json()["acertou"] is False

    # Buscar o resposta_id no banco
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id FROM questoes_respostas WHERE questao_id = ? ORDER BY id DESC LIMIT 1",
        (questao_id,)
    ).fetchone()
    conn.close()
    return row["id"]


class TestErrorAnalysis:
    """Testes dos endpoints /api/questoes/erros/analise."""

    def test_create_analysis(self, client):
        """Criar análise de erro com motivo válido."""
        resposta_id = _create_questao_and_resposta(client)
        r = client.post("/api/questoes/erros/analise", json={
            "resposta_id": resposta_id,
            "motivo": "conceito_errado",
            "detalhe": "Confundi soberania com dignidade"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["id"] >= 1
        assert data["updated"] is False

    def test_invalid_motivo(self, client):
        """Motivo inválido deve retornar 400."""
        resposta_id = _create_questao_and_resposta(client)
        r = client.post("/api/questoes/erros/analise", json={
            "resposta_id": resposta_id,
            "motivo": "preguica",
            "detalhe": "Motivo inexistente"
        })
        assert r.status_code == 400
        assert "Motivo inválido" in r.json()["detail"]

    def test_update_existing(self, client):
        """Atualizar análise existente (mesmo resposta_id) deve retornar updated=True."""
        resposta_id = _create_questao_and_resposta(client)

        # Criar análise inicial
        r = client.post("/api/questoes/erros/analise", json={
            "resposta_id": resposta_id,
            "motivo": "chute",
            "detalhe": "Não sabia nada"
        })
        assert r.status_code == 200
        assert r.json()["updated"] is False

        # Atualizar
        r = client.post("/api/questoes/erros/analise", json={
            "resposta_id": resposta_id,
            "motivo": "leitura_incompleta",
            "detalhe": "Na verdade li rápido demais"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["updated"] is True

    def test_get_stats(self, client):
        """Stats devem retornar estrutura correta mesmo sem dados."""
        r = client.get("/api/questoes/erros/analise/stats")
        assert r.status_code == 200
        data = r.json()
        assert "total_analisados" in data
        assert "stats" in data
        assert "top_motivo" in data
        assert "dica" in data
        assert isinstance(data["stats"], list)

    def test_get_by_resposta(self, client):
        """Consulta individual por resposta_id."""
        resposta_id = _create_questao_and_resposta(client)

        # Sem análise → found=False
        r = client.get(f"/api/questoes/erros/analise/{resposta_id}")
        assert r.status_code == 200
        assert r.json()["found"] is False

        # Criar análise
        client.post("/api/questoes/erros/analise", json={
            "resposta_id": resposta_id,
            "motivo": "pegadinha",
            "detalhe": "Dupla negação no enunciado"
        })

        # Agora deve retornar found=True
        r = client.get(f"/api/questoes/erros/analise/{resposta_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["found"] is True
        assert data["motivo"] == "pegadinha"
        assert data["detalhe"] == "Dupla negação no enunciado"

    def test_delete_analysis(self, client):
        """Remover análise de erro."""
        resposta_id = _create_questao_and_resposta(client)

        # Criar análise
        client.post("/api/questoes/erros/analise", json={
            "resposta_id": resposta_id,
            "motivo": "desatencao",
            "detalhe": "Marquei errado"
        })

        # Deletar
        r = client.delete(f"/api/questoes/erros/analise/{resposta_id}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Confirmar que foi removida
        r = client.get(f"/api/questoes/erros/analise/{resposta_id}")
        assert r.status_code == 200
        assert r.json()["found"] is False

    def test_stats_with_data(self, client):
        """Stats com dados devem incluir percentuais e dicas."""
        # Criar múltiplas análises com motivos diferentes
        for motivo in ["conceito_errado", "conceito_errado", "pegadinha"]:
            resposta_id = _create_questao_and_resposta(client)
            r = client.post("/api/questoes/erros/analise", json={
                "resposta_id": resposta_id,
                "motivo": motivo,
                "detalhe": f"Erro por {motivo}"
            })
            assert r.status_code == 200

        r = client.get("/api/questoes/erros/analise/stats")
        assert r.status_code == 200
        data = r.json()

        assert data["total_analisados"] >= 3
        assert len(data["stats"]) >= 2
        assert data["top_motivo"] is not None
        assert data["dica"] is not None
        assert "💡" in data["dica"]

        # Verificar que cada stat tem percentual
        for stat in data["stats"]:
            assert "motivo" in stat
            assert "total" in stat
            assert "percentual" in stat
            assert stat["percentual"] >= 0
            assert stat["percentual"] <= 100

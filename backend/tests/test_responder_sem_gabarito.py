"""Testes do endpoint POST /api/questoes/{id}/responder para questões SEM gabarito.

Regressão: questões com resposta_correta vazia marcavam SEMPRE "errou"
(comparação com string vazia), independente da alternativa escolhida.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_resp_semgab.db", delete=False)
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


def _criar_questao(resposta_correta: str) -> int:
    """Insere questão certo/errado diretamente no DB e retorna o id."""
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "created_at, user_id) VALUES (?, '', ?, 'CERTO', 'ERRADO', '', '', '', ?, '', 'Médio', '2026-01-01', 1)",
            ("Informática", "Item de exemplo certo/errado.", resposta_correta),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


class TestResponderSemGabarito:
    def test_sem_gabarito_nao_marca_erro_marcando_certo(self, client):
        qid = _criar_questao("")  # sem gabarito
        r = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 10})
        assert r.status_code == 200
        data = r.json()
        assert data["sem_gabarito"] is True
        assert data["acertou"] is None  # não penaliza

    def test_sem_gabarito_nao_marca_erro_marcando_errado(self, client):
        qid = _criar_questao("")  # sem gabarito
        r = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "B", "tempo_segundos": 10})
        assert r.status_code == 200
        data = r.json()
        assert data["sem_gabarito"] is True
        assert data["acertou"] is None

    def test_sem_gabarito_nao_registra_resposta(self, client):
        qid = _criar_questao("")
        client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 10})
        c = sqlite3.connect(_tmp_db.name, timeout=10)
        try:
            n = c.execute(
                "SELECT COUNT(*) FROM questoes_respostas WHERE questao_id = ?", (qid,)
            ).fetchone()[0]
        finally:
            c.close()
        assert n == 0  # nenhuma resposta gravada para questão sem gabarito

    def test_com_gabarito_certo_acerta(self, client):
        qid = _criar_questao("A")  # gabarito = CERTO
        r = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 10})
        assert r.status_code == 200
        data = r.json()
        assert data["acertou"] is True
        assert data.get("sem_gabarito") is False

    def test_com_gabarito_errado_erra(self, client):
        qid = _criar_questao("B")  # gabarito = ERRADO
        r = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 10})
        assert r.status_code == 200
        data = r.json()
        assert data["acertou"] is False
        assert data["resposta_correta"] == "B"

"""Regressão: correções do logout no meio da sessão e retomada do CAT.

A) POST /api/auth/refresh — renova o access token via refresh token (o
   auth-interceptor usa isso para não deslogar quando o access token de 1h expira).
B) GET /api/sessao-adaptativa/ativa — retorna a sessão adaptativa 'ativa' para
   retomar (em vez de perder a continuidade após uma interrupção).

Executar: pytest tests/test_auth_refresh_cat.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_auth_refresh.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app
from settings import settings

from routers.auth import _create_access_token, _create_refresh_token


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
    settings.AUTH_ENABLED = True
    app.dependency_overrides[get_db_session] = _override_db_session
    # Garante um usuário (id=1) para os tokens.
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("INSERT OR IGNORE INTO users (id, email, nome) VALUES (1, 'user@test.com', 'User')")
        c.commit()
    finally:
        c.close()
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.pop(get_db_session, None)
    # Reset do flag global para NÃO poluir outros módulos de teste (ex.: test_batalha
    # roda sem auth). Sem isto, AUTH_ENABLED=True vazava e quebrava a criação de
    # questões de outros testes com 401.
    settings.AUTH_ENABLED = False


# ---- A) Refresh token -------------------------------------------------------

def test_refresh_renova_access_token(client):
    refresh = _create_refresh_token(1)
    r = client.post("/api/auth/refresh", json={"refresh_token": refresh})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data.get("access_token")
    assert data.get("refresh_token")  # token rotation


def test_refresh_com_access_token_e_rejeitado(client):
    """Um access token não pode ser usado como refresh (type != 'refresh')."""
    access = _create_access_token(1, "user@test.com")
    r = client.post("/api/auth/refresh", json={"refresh_token": access})
    assert r.status_code == 401


def test_refresh_invalido_401(client):
    r = client.post("/api/auth/refresh", json={"refresh_token": "nao-e-um-token"})
    assert r.status_code == 401


# ---- B) Sessão adaptativa ativa (retomar) -----------------------------------

def test_sessao_ativa_vazia(client):
    token = _create_access_token(1, "user@test.com")
    h = {"Authorization": f"Bearer {token}"}
    # Sem sessão ativa.
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM sessao_adaptativa WHERE user_id = 1")
        c.commit()
    finally:
        c.close()
    r = client.get("/api/sessao-adaptativa/ativa", headers=h)
    assert r.status_code == 200
    assert r.json()["ativa"] is False


def test_sessao_ativa_retorna_a_pendente(client):
    token = _create_access_token(1, "user@test.com")
    h = {"Authorization": f"Bearer {token}"}
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM sessao_adaptativa WHERE user_id = 1")
        c.execute(
            "INSERT INTO sessao_adaptativa (user_id, session_id, materia, theta, "
            "questoes_respondidas, acertos, dificuldade_atual, status, started_at) "
            "VALUES (1, 'sess-1', 'Informática', 0.5, 9, 6, 'Médio', 'ativa', '2026-01-01')"
        )
        c.commit()
    finally:
        c.close()
    r = client.get("/api/sessao-adaptativa/ativa", headers=h)
    assert r.status_code == 200
    d = r.json()
    assert d["ativa"] is True
    assert d["session_id"] == "sess-1"
    assert d["questoes_respondidas"] == 9
    assert d["acertos"] == 6


def test_sessao_finalizada_nao_e_retomada(client):
    token = _create_access_token(1, "user@test.com")
    h = {"Authorization": f"Bearer {token}"}
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM sessao_adaptativa WHERE user_id = 1")
        c.execute(
            "INSERT INTO sessao_adaptativa (user_id, session_id, materia, theta, "
            "questoes_respondidas, acertos, dificuldade_atual, status, started_at) "
            "VALUES (1, 'sess-fim', 'X', 0.0, 3, 2, 'Médio', 'finalizada', '2026-01-01')"
        )
        c.commit()
    finally:
        c.close()
    r = client.get("/api/sessao-adaptativa/ativa", headers=h)
    assert r.json()["ativa"] is False


# ---- C) Resposta da CAT conta para as questões do dia -----------------------

def test_resposta_cat_conta_em_questoes_respostas(client):
    """Ao responder na Sessão Adaptativa, a resposta também deve ser gravada em
    questoes_respostas (conta no dia, alimenta streak e exclui do Daily Challenge)."""
    token = _create_access_token(1, "user@test.com")
    h = {"Authorization": f"Bearer {token}"}
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM sessao_adaptativa WHERE user_id = 1")
        c.execute("DELETE FROM sessao_adaptativa_respostas")
        c.execute("DELETE FROM questoes_respostas WHERE user_id = 1")
        c.execute("DELETE FROM questoes WHERE user_id = 1")
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, dificuldade, tipo, created_at, user_id) "
            "VALUES ('X', '', 'Enun CAT', 'A', 'B', 'C', 'D', '', 'A', 'Médio', 'objetiva', '2026-01-01', 1)"
        )
        qid = cur.lastrowid
        # Sessão ativa manual
        c.execute(
            "INSERT INTO sessao_adaptativa (user_id, session_id, materia, theta, "
            "questoes_respondidas, acertos, dificuldade_atual, status, started_at) "
            "VALUES (1, 'sess-cat', 'X', 0.0, 0, 0, 'Médio', 'ativa', '2026-01-01')"
        )
        c.commit()
    finally:
        c.close()

    r = client.post("/api/sessao-adaptativa/sess-cat/responder",
                    json={"questao_id": qid, "resposta": "A", "tempo_ms": 5000}, headers=h)
    assert r.status_code == 200, r.text

    # Deve ter criado UMA linha em questoes_respostas hoje para essa questão.
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        n = c.execute(
            "SELECT COUNT(*) FROM questoes_respostas WHERE questao_id = ? AND user_id = 1 AND data = date('now')",
            (qid,),
        ).fetchone()[0]
        assert n == 1, "resposta da CAT não foi contabilizada em questoes_respostas"

        # Daily-challenge não deve mais oferecer essa questão (respondida hoje).
        # Como é a única questão, o desafio fica sem questão.
    finally:
        c.close()
    dc = client.get("/api/daily-challenge", headers=h)
    assert dc.status_code == 200
    assert dc.json().get("questao") is None, "questão respondida na CAT reapareceu no Daily Challenge"

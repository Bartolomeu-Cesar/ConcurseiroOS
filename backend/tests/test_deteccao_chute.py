"""Testes da detecção de chutes ao resolver questões.

Cobre:
- Helper _classificar_chute (tempo abaixo do limiar / baixa confiança).
- POST /api/questoes/{id}/responder retorna chute=True quando acerta rápido demais.
- GET /api/questoes/chutes (estatística geral e por matéria).

Executar: pytest tests/test_deteccao_chute.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_chute.db", delete=False)
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

_UID = 1


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


def _criar_questao(correta="A", dificuldade="Médio"):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "created_at, user_id) VALUES ('DirChute', '', 'Enun', 'a', 'b', 'c', 'd', '', ?, '', ?, '2026-01-01', ?)",
            (correta, dificuldade, _UID),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


# ---------- Helper unitário ----------

def test_classificar_chute_rapido_demais():
    from routers.questoes.core import _classificar_chute
    # Acertou em 3s numa questão Média (limiar 12s) → chute
    r = _classificar_chute(1, 3, None, "Médio")
    assert r["chute"] is True
    assert r["categoria"] == "chute_sortudo"
    assert r["mensagem"]


def test_classificar_chute_acerto_solido():
    from routers.questoes.core import _classificar_chute
    # Acertou em 40s (bem acima do limiar) → sólido
    r = _classificar_chute(1, 40, None, "Médio")
    assert r["chute"] is False
    assert r["categoria"] == "acerto_solido"


def test_classificar_chute_baixa_confianca():
    from routers.questoes.core import _classificar_chute
    # Acertou com tempo ok mas confiança 1 (chutei) → chute
    r = _classificar_chute(1, 40, 1, "Médio")
    assert r["chute"] is True


def test_classificar_chute_erro_nao_e_chute():
    from routers.questoes.core import _classificar_chute
    r = _classificar_chute(0, 2, None, "Médio")
    assert r["chute"] is False
    assert r["categoria"] == "erro"


# ---------- Endpoint responder ----------

def test_responder_acerto_rapido_marca_chute(client):
    qid = _criar_questao(correta="A", dificuldade="Médio")
    r = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 2})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["acertou"] is True
    assert d["chute"] is True
    assert "chute_mensagem" in d


def test_responder_acerto_lento_nao_marca_chute(client):
    qid = _criar_questao(correta="B", dificuldade="Médio")
    r = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "B", "tempo_segundos": 60})
    d = r.json()
    assert d["acertou"] is True
    assert d["chute"] is False


def test_responder_erro_nao_marca_chute(client):
    qid = _criar_questao(correta="C", dificuldade="Médio")
    r = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 2})
    d = r.json()
    assert d["acertou"] is False
    assert d["chute"] is False


# ---------- Endpoint de estatística ----------

def test_stats_chutes(client):
    # 1 acerto chutado (rápido) + 1 acerto sólido (lento) na mesma matéria nova
    q1 = _criar_questao(correta="A", dificuldade="Fácil")   # limiar 8s
    q2 = _criar_questao(correta="A", dificuldade="Fácil")
    client.post(f"/api/questoes/{q1}/responder", json={"resposta": "A", "tempo_segundos": 2})   # chute
    client.post(f"/api/questoes/{q2}/responder", json={"resposta": "A", "tempo_segundos": 30})  # sólido

    r = client.get("/api/questoes/chutes")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["acertos"] >= 2
    assert d["chutes"] >= 1
    assert 0 <= d["pct_chute_sobre_acertos"] <= 100
    assert any(m["materia"] == "DirChute" for m in d["por_materia"])


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

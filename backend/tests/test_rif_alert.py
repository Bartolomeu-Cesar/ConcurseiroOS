"""Testes do alerta de Retrieval-Induced Forgetting (RIF) — study_intelligence.

Executar: pytest tests/test_rif_alert.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_rif.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["TEST_DB"] = _tmp_db.name

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from deps import get_user_id
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


async def _override_uid():
    return _UID


client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_user_id] = _override_uid
    yield
    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_user_id, None)


def _mk_questao(c, materia, topico):
    cur = c.execute(
        "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
        "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
        "created_at, user_id) VALUES (?,?,'E','a','b','c','d','','A','','Médio','2026-01-01',?)",
        (materia, topico, _UID),
    )
    return cur.lastrowid


def _responder(c, qid, n):
    for _ in range(n):
        c.execute(
            "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id) "
            "VALUES (?, 'A', 1, 10, '2026-01-01', ?)",
            (qid, _UID),
        )


def test_rif_detecta_topico_negligenciado():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        # Matéria no ciclo ativo.
        c.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('RifMat', 1, ?)", (_UID,))
        q_dom = _mk_questao(c, "RifMat", "TopicoDominante")
        q_neg = _mk_questao(c, "RifMat", "TopicoNegligenciado")
        _responder(c, q_dom, 10)  # muito praticado
        _responder(c, q_neg, 1)   # quase nada → <= 25% de 10
        c.commit()
    finally:
        c.close()
    r = client.get("/api/study-intelligence/retrieval-induced-forgetting")
    assert r.status_code == 200
    b = r.json()
    assert b["total_alertas"] >= 1
    topicos_alerta = [a["topico"] for a in b["alertas"]]
    assert "TopicoNegligenciado" in topicos_alerta


def test_rif_ignora_materia_fora_do_ciclo_ativo():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        # Matéria INATIVA no ciclo — não deve gerar alerta.
        c.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('InativaMat', 0, ?)", (_UID,))
        q_dom = _mk_questao(c, "InativaMat", "Dom")
        q_neg = _mk_questao(c, "InativaMat", "Neg")
        _responder(c, q_dom, 10)
        _responder(c, q_neg, 1)
        c.commit()
    finally:
        c.close()
    r = client.get("/api/study-intelligence/retrieval-induced-forgetting")
    assert r.status_code == 200
    # Matéria inativa deve ser filtrada — nenhum alerta dela.
    assert all(a["materia"] != "InativaMat" for a in r.json()["alertas"])


def test_rif_pratica_equilibrada_sem_alerta():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES ('Equilibrada', 1, ?)", (_UID,))
        q1 = _mk_questao(c, "Equilibrada", "T1")
        q2 = _mk_questao(c, "Equilibrada", "T2")
        _responder(c, q1, 5)
        _responder(c, q2, 5)  # equilibrado → sem supressão relativa
        c.commit()
    finally:
        c.close()
    r = client.get("/api/study-intelligence/retrieval-induced-forgetting")
    assert r.status_code == 200
    # Nenhum alerta para a matéria equilibrada.
    assert all(a["materia"] != "Equilibrada" for a in r.json()["alertas"])

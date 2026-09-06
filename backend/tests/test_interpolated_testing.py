"""Testes do Interpolated Testing — study_intelligence.

Executar: pytest tests/test_interpolated_testing.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_interp.db", delete=False)
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


def _seed(materia="Interp", com_flashcard=True, com_questao=True):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        if com_flashcard:
            c.execute(
                "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id) "
                "VALUES ('P1?','R1','2026-01-01',?,?)",
                (materia, _UID),
            )
        if com_questao:
            c.execute(
                "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
                "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
                "created_at, user_id) VALUES (?,'','Enun','a','b','c','d','','A','','Médio','2026-01-01',?)",
                (materia, _UID),
            )
        c.commit()
    finally:
        c.close()


def test_interpolated_retorna_itens():
    _seed(materia="Interp1")
    r = client.get("/api/study-intelligence/interpolated-test", params={"materia": "Interp1", "quantidade": 2})
    assert r.status_code == 200
    b = r.json()
    assert b["disponivel"] is True
    assert 1 <= len(b["itens"]) <= 2


def test_interpolated_prioriza_flashcard():
    _seed(materia="Interp2", com_flashcard=True, com_questao=True)
    r = client.get("/api/study-intelligence/interpolated-test", params={"materia": "Interp2", "quantidade": 1})
    assert r.status_code == 200
    itens = r.json()["itens"]
    assert len(itens) == 1
    assert itens[0]["tipo"] == "flashcard"


def test_interpolated_completa_com_questao():
    # Só questão disponível → deve cair no fallback de questão.
    _seed(materia="Interp3", com_flashcard=False, com_questao=True)
    r = client.get("/api/study-intelligence/interpolated-test", params={"materia": "Interp3", "quantidade": 2})
    assert r.status_code == 200
    itens = r.json()["itens"]
    assert len(itens) >= 1
    assert any(i["tipo"] == "questao" for i in itens)


def test_interpolated_sem_conteudo_indisponivel():
    r = client.get("/api/study-intelligence/interpolated-test", params={"materia": "MateriaVazia"})
    assert r.status_code == 200
    b = r.json()
    assert b["disponivel"] is False
    assert b["itens"] == []


def test_interpolated_materia_obrigatoria_422():
    r = client.get("/api/study-intelligence/interpolated-test")
    assert r.status_code == 422

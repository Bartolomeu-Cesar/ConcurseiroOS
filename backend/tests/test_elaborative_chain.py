"""Testes da Elaborative Interrogation encadeada — study_intelligence.

Executar: pytest tests/test_elaborative_chain.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_eichain.db", delete=False)
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


def test_chain_gera_niveis_default():
    r = client.get("/api/study-intelligence/elaborative-chain", params={"conceito": "Princípio da Legalidade"})
    assert r.status_code == 200
    b = r.json()
    assert b["profundidade"] == 4
    assert len(b["niveis"]) == 4
    # Níveis numerados em ordem 1..N.
    assert [n["nivel"] for n in b["niveis"]] == [1, 2, 3, 4]
    # O primeiro prompt menciona o conceito.
    assert "Princípio da Legalidade" in b["niveis"][0]["prompt"]


def test_chain_respeita_profundidade():
    r = client.get("/api/study-intelligence/elaborative-chain", params={"conceito": "Dolo", "profundidade": 6})
    assert r.status_code == 200
    assert len(r.json()["niveis"]) == 6


def test_chain_profundidade_fora_do_range_422():
    r = client.get("/api/study-intelligence/elaborative-chain", params={"conceito": "Dolo", "profundidade": 99})
    assert r.status_code == 422


def test_chain_conceito_vazio_400():
    r = client.get("/api/study-intelligence/elaborative-chain", params={"conceito": "   "})
    assert r.status_code == 400


def test_chain_conceito_obrigatorio_422():
    r = client.get("/api/study-intelligence/elaborative-chain")
    assert r.status_code == 422


def test_chain_ancora_do_edital():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute(
            "INSERT INTO edital (materia, topico, status, arquivado, user_id) "
            "VALUES ('DirAdm','Legalidade administrativa','Pendente',0,?)",
            (_UID,),
        )
        c.commit()
    finally:
        c.close()
    r = client.get(
        "/api/study-intelligence/elaborative-chain",
        params={"conceito": "Legalidade", "materia": "DirAdm"},
    )
    assert r.status_code == 200
    assert r.json()["ancora"] is not None
    assert r.json()["ancora"]["tipo"] == "topico_edital"

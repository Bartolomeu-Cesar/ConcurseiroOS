"""Testes do Closed-book antes de open-book — study_intelligence.

Executar: pytest tests/test_closed_book.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_closedbook.db", delete=False)
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


def _seed_edital_flashcards():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute(
            "INSERT INTO edital (materia, topico, status, arquivado, user_id) VALUES ('Dir','Princípios','Pendente',0,?)",
            (_UID,),
        )
        c.execute(
            "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id) "
            "VALUES ('O que é legalidade?','...', '2026-01-01', 'Dir', ?)",
            (_UID,),
        )
        c.commit()
    finally:
        c.close()


def test_closed_book_prompt_ok():
    _seed_edital_flashcards()
    r = client.get("/api/study-intelligence/closed-book", params={"materia": "Dir"})
    assert r.status_code == 200
    b = r.json()
    assert b["modo"] == "closed_book"
    assert isinstance(b["ancoras"], list)
    # Deve ter puxado ao menos uma âncora (edital ou flashcard) da matéria semeada.
    assert len(b["ancoras"]) >= 1


def test_closed_book_prompt_sem_materia_422():
    # materia é query param obrigatório → FastAPI retorna 422 se ausente.
    r = client.get("/api/study-intelligence/closed-book")
    assert r.status_code == 422


def test_closed_book_resultado_recall_alto():
    r = client.post("/api/study-intelligence/closed-book/resultado", json={"materia": "Dir", "auto_recall": 85})
    assert r.status_code == 200
    b = r.json()
    assert b["open_book_liberado"] is True
    assert b["id"] > 0


def test_closed_book_resultado_recall_baixo_mensagem():
    r = client.post("/api/study-intelligence/closed-book/resultado", json={"materia": "Dir", "auto_recall": 10})
    assert r.status_code == 200
    assert "lacuna" in r.json()["mensagem"].lower()


def test_closed_book_resultado_sem_materia_400():
    r = client.post("/api/study-intelligence/closed-book/resultado", json={"auto_recall": 50})
    assert r.status_code == 400


def test_closed_book_resultado_recall_invalido_400():
    r = client.post("/api/study-intelligence/closed-book/resultado", json={"materia": "Dir", "auto_recall": "abc"})
    assert r.status_code == 400


def test_closed_book_resultado_sem_recall_ok():
    # auto_recall é opcional; sem ele ainda registra e libera open-book.
    r = client.post("/api/study-intelligence/closed-book/resultado", json={"materia": "Dir"})
    assert r.status_code == 200
    assert r.json()["open_book_liberado"] is True

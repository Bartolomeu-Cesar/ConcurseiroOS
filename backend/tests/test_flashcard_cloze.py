"""Testes do Cloze deletion nativo (estilo Anki):
- parse_cloze_nativo: 1 card por número de lacuna (c1, c2...), dica, sem cloze.
- POST /api/flashcards/cloze: cria N cards, valida texto sem lacuna, salva cloze_text.
- Cards cloze entram na fila /today e são revisáveis normalmente.

Executar: pytest tests/test_flashcard_cloze.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_cloze.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["TEST_DB"] = _tmp_db.name

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient

from deps import get_user_id
from main import app
from routers.flashcards import parse_cloze_nativo

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
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM flashcards")
    conn.commit()
    conn.close()
    yield
    app.dependency_overrides.pop(get_user_id, None)


# ==================== PARSING ====================


def test_uma_lacuna():
    cards = parse_cloze_nativo("O prazo do MS é {{c1::120 dias}}")
    assert len(cards) == 1
    assert cards[0]["pergunta"] == "O prazo do MS é [...]"
    assert cards[0]["resposta"] == "120 dias"


def test_multiplos_grupos_geram_multiplos_cards():
    cards = parse_cloze_nativo("Art. 5º {{c1::todos}} são iguais perante a {{c2::lei}}")
    assert len(cards) == 2
    c1 = next(c for c in cards if c["numero"] == 1)
    c2 = next(c for c in cards if c["numero"] == 2)
    # No card c1: c1 oculto, c2 revelado
    assert "[...]" in c1["pergunta"]
    assert "lei" in c1["pergunta"]
    assert c1["resposta"] == "todos"
    # No card c2: c2 oculto, c1 revelado
    assert "[...]" in c2["pergunta"]
    assert "todos" in c2["pergunta"]
    assert c2["resposta"] == "lei"


def test_mesma_lacuna_repetida_une_respostas():
    cards = parse_cloze_nativo("{{c1::A}} e {{c1::B}} juntos")
    assert len(cards) == 1
    assert cards[0]["resposta"] == "A / B"
    assert cards[0]["pergunta"].count("[...]") == 2


def test_dica_aparece_na_lacuna():
    cards = parse_cloze_nativo("A capital é {{c1::São Luís::cidade}}")
    assert len(cards) == 1
    assert cards[0]["pergunta"] == "A capital é [cidade]"
    assert cards[0]["resposta"] == "São Luís"


def test_sem_cloze_retorna_vazio():
    assert parse_cloze_nativo("texto normal sem lacuna") == []
    assert parse_cloze_nativo("") == []


# ==================== ENDPOINT ====================


def test_endpoint_cria_n_cards():
    r = client.post(
        "/api/flashcards/cloze",
        json={
            "texto": "Art. 5º {{c1::todos}} são iguais perante a {{c2::lei}}",
            "materia": "Dir Const",
        },
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["criados"] == 2
    assert len(data["ids"]) == 2


def test_endpoint_salva_cloze_text_e_materia():
    client.post("/api/flashcards/cloze", json={"texto": "X {{c1::y}}", "materia": "Mat"})
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    row = conn.execute("SELECT cloze_text, materia FROM flashcards LIMIT 1").fetchone()
    conn.close()
    assert row[0] == "X {{c1::y}}"
    assert row[1] == "Mat"


def test_endpoint_texto_sem_lacuna_400():
    r = client.post("/api/flashcards/cloze", json={"texto": "sem lacuna aqui"})
    assert r.status_code == 400


def test_endpoint_texto_vazio_400():
    r = client.post("/api/flashcards/cloze", json={"texto": "   "})
    assert r.status_code == 400


def test_cards_cloze_aparecem_no_today():
    client.post("/api/flashcards/cloze", json={"texto": "Art. 1 {{c1::soberania}}"})
    cards = client.get("/api/flashcards/today").json()
    perguntas = [c["pergunta"] for c in cards]
    assert any("[...]" in p for p in perguntas)


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

"""Testes de cards reversos (note type básico frente↔verso, à la Anki):
- reverso=True cria 2 cards (frente P->R + verso R->P) com o mesmo note_id.
- reverso ausente/False cria 1 card normal (retrocompat).
- Os dois cards são revisáveis independentemente e excluir um não afeta o irmão.

Executar: pytest tests/test_flashcard_reverso.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_reverso.db", delete=False)
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


def _row(fid):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM flashcards WHERE id = ?", (fid,)).fetchone()
    conn.close()
    return dict(r) if r else None


# ==================== CRIAÇÃO ====================


def test_reverso_cria_dois_cards():
    r = client.post(
        "/api/flashcards",
        json={
            "pergunta": "Capital do MA?",
            "resposta": "São Luís",
            "materia": "Geo",
            "reverso": True,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["criados"] == 2
    assert len(data["ids"]) == 2


def test_reverso_inverte_pergunta_resposta():
    data = client.post(
        "/api/flashcards",
        json={
            "pergunta": "P",
            "resposta": "R",
            "reverso": True,
        },
    ).json()
    frente_id, verso_id = data["ids"]
    frente, verso = _row(frente_id), _row(verso_id)
    assert frente["pergunta"] == "P" and frente["resposta"] == "R"
    assert frente["card_tipo"] == "frente"
    assert verso["pergunta"] == "R" and verso["resposta"] == "P"
    assert verso["card_tipo"] == "verso"


def test_irmaos_compartilham_note_id():
    data = client.post(
        "/api/flashcards",
        json={
            "pergunta": "P",
            "resposta": "R",
            "reverso": True,
        },
    ).json()
    frente, verso = _row(data["ids"][0]), _row(data["ids"][1])
    assert frente["note_id"] == verso["note_id"]
    assert frente["note_id"] == frente["id"]  # note_id = id do primeiro card


def test_sem_reverso_cria_um_card_normal():
    r = client.post("/api/flashcards", json={"pergunta": "2+2", "resposta": "4"})
    data = r.json()
    assert data.get("criados", 1) == 1
    card = _row(data["id"])
    assert card["card_tipo"] == "normal"
    assert card["note_id"] == card["id"]


def test_retrocompat_sem_campo_reverso():
    # Payload sem o campo 'reverso' — deve funcionar como antes (1 card).
    r = client.post("/api/flashcards", json={"pergunta": "X", "resposta": "Y", "materia": "M"})
    assert r.status_code == 200
    assert r.json().get("criados", 1) == 1


# ==================== INDEPENDÊNCIA / CONSISTÊNCIA ====================


def test_ambos_aparecem_no_today():
    data = client.post(
        "/api/flashcards",
        json={
            "pergunta": "P",
            "resposta": "R",
            "reverso": True,
        },
    ).json()
    ids_today = {c["id"] for c in client.get("/api/flashcards/today").json()}
    assert set(data["ids"]).issubset(ids_today)


def test_revisar_um_nao_afeta_o_irmao():
    data = client.post(
        "/api/flashcards",
        json={
            "pergunta": "P",
            "resposta": "R",
            "reverso": True,
        },
    ).json()
    frente_id, verso_id = data["ids"]
    # Revisa só a frente (Good)
    client.post(f"/api/flashcards/{frente_id}/review-fsrs", json={"quality": 4})
    frente, verso = _row(frente_id), _row(verso_id)
    # Frente avançou (repetitions/intervalo), verso permanece intacto
    assert (frente["repetitions"] or 0) >= 1
    assert (verso["repetitions"] or 0) == 0


def test_excluir_um_nao_apaga_o_irmao():
    data = client.post(
        "/api/flashcards",
        json={
            "pergunta": "P",
            "resposta": "R",
            "reverso": True,
        },
    ).json()
    frente_id, verso_id = data["ids"]
    r = client.delete(f"/api/flashcards/{frente_id}")
    assert r.status_code == 200
    assert _row(frente_id) is None  # frente apagada
    assert _row(verso_id) is not None  # verso permanece


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

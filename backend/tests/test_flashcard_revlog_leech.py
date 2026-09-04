"""Testes da fundação 'Anki-like' de flashcards:
- Review log (flashcard_revlog): 1 linha por revisão.
- Leech detection: lapses em Again, is_leech no limite, suspenso no múltiplo.
- Retenção real (/api/flashcards/retencao-real): acerto em cards maduros + forecast.
- Cards suspensos saem da fila /today.

Executar: pytest tests/test_flashcard_revlog_leech.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_revlog.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["TEST_DB"] = _tmp_db.name

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from constants import LEECH_SUSPEND_MULTIPLE, LEECH_THRESHOLD
from fastapi.testclient import TestClient

from deps import get_user_id
from main import app
from utils import today_str

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
    conn.execute("DELETE FROM flashcard_revlog")
    conn.commit()
    conn.close()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def _novo_flashcard(fid, intervalo=1, reps=0, stability=0.0, fsrs_state=0):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id, stability, difficulty, fsrs_state) "
        "VALUES (?, 'P', 'R', ?, ?, 2.5, ?, ?, ?, 3, ?)",
        (fid, today_str(), intervalo, reps, _UID, stability, fsrs_state),
    )
    conn.commit()
    conn.close()


def _revlog_count(fid):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    n = conn.execute("SELECT COUNT(*) FROM flashcard_revlog WHERE flashcard_id = ?", (fid,)).fetchone()[0]
    conn.close()
    return n


# ==================== REVLOG ====================


def test_review_grava_no_revlog():
    _novo_flashcard(1)
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.status_code == 200
    assert _revlog_count(1) == 1


def test_cada_review_gera_uma_linha():
    _novo_flashcard(1)
    for q in (4, 3, 4):
        client.post("/api/flashcards/1/review-fsrs", json={"quality": q})
    assert _revlog_count(1) == 3


def test_revlog_registra_rating_e_estado():
    _novo_flashcard(1)
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})  # Good/Easy
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    row = conn.execute(
        "SELECT rating, quality, estado_depois, intervalo_dias FROM flashcard_revlog WHERE flashcard_id = 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] >= 3  # rating Good/Easy
    assert row[1] == 4  # quality original
    assert row[3] >= 1  # intervalo agendado


# ==================== LEECH ====================


def test_again_incrementa_lapses():
    _novo_flashcard(1)
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})  # Again
    assert r.json()["lapses"] == 1
    assert r.json()["is_leech"] is False


def test_acerto_nao_incrementa_lapses():
    _novo_flashcard(1)
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})  # Good
    assert r.json()["lapses"] == 0


def test_vira_leech_no_limite():
    _novo_flashcard(1)
    r = None
    for _ in range(LEECH_THRESHOLD):
        r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})
    assert r.json()["lapses"] == LEECH_THRESHOLD
    assert r.json()["is_leech"] is True
    assert r.json()["leech_now"] is True  # sinaliza que virou leech AGORA


def test_suspende_no_multiplo():
    _novo_flashcard(1)
    r = None
    for _ in range(LEECH_THRESHOLD * LEECH_SUSPEND_MULTIPLE):
        r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})
    assert r.json()["suspenso"] is True


def test_card_suspenso_sai_da_fila_today():
    _novo_flashcard(1)
    _novo_flashcard(2)
    # Suspende o card 1
    for _ in range(LEECH_THRESHOLD * LEECH_SUSPEND_MULTIPLE):
        client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})
    ids = [c["id"] for c in client.get("/api/flashcards/today").json()]
    assert 1 not in ids  # suspenso não aparece
    # (o card 2 pode ou não estar dependendo do agendamento, mas 1 nunca)


def test_today_expoe_is_leech_booleano():
    _novo_flashcard(1)
    for _ in range(LEECH_THRESHOLD):
        client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})
    # Card virou leech mas ainda não suspenso → aparece com is_leech True
    cards = client.get("/api/flashcards/today").json()
    card1 = next((c for c in cards if c["id"] == 1), None)
    if card1 is not None:  # se ainda vencido hoje
        assert card1["is_leech"] is True


# ==================== RETENÇÃO REAL ====================


def test_retencao_real_sem_dados():
    r = client.get("/api/flashcards/retencao-real")
    assert r.status_code == 200
    data = r.json()
    assert data["true_retention"] is None  # sem reviews maduros
    assert data["reviews_total"] == 0
    assert data["forecast"] == []


def test_true_retention_conta_so_cards_maduros():
    # Card maduro (intervalo 30d >= 21d) acertado → true_retention 100%
    _novo_flashcard(1, intervalo=30, reps=3, stability=40, fsrs_state=2)
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    # Card novo (intervalo 1d) errado → NÃO entra na true_retention
    _novo_flashcard(2, intervalo=1)
    client.post("/api/flashcards/2/review-fsrs", json={"quality": 0})

    data = client.get("/api/flashcards/retencao-real").json()
    assert data["reviews_maduros"] == 1
    assert data["true_retention"] == 100.0  # só o maduro conta
    assert data["reviews_total"] == 2  # geral conta os dois


def test_retencao_real_conta_leech():
    _novo_flashcard(1)
    for _ in range(LEECH_THRESHOLD):
        client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})
    data = client.get("/api/flashcards/retencao-real").json()
    assert data["leech_count"] == 1


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

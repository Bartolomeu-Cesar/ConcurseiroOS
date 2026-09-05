"""Testes do Undo de review de flashcards (à la Anki, item #9 do roadmap).

Cobre:
- Endpoint POST /api/flashcards/{id}/undo-review restaura o estado FSRS anterior
  do card (intervalo, proxima_revisao, stability, difficulty, fsrs_state,
  repetitions, lapses) e apaga a última linha do revlog.
- Undo repetido desfaz revisões sucessivas (LIFO).
- 404 para card inexistente; 400 sem revisão para desfazer; 400 para linha sem
  snapshot (revisão anterior à migration 80).
- Não vaza entre usuários.

Executar: pytest tests/test_flashcard_undo.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_undo.db", delete=False)
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


def _novo_flashcard(fid, intervalo=5, reps=2, stability=12.3, difficulty=4.5, fsrs_state=2, uid=_UID):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id, stability, difficulty, fsrs_state) "
        "VALUES (?, 'P', 'R', ?, ?, 2.5, ?, ?, ?, ?, ?)",
        (fid, today_str(), intervalo, reps, uid, stability, difficulty, fsrs_state),
    )
    conn.commit()
    conn.close()


def _card_estado(fid):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    r = conn.execute(
        "SELECT intervalo_dias, proxima_revisao, repetitions, stability, difficulty, fsrs_state, lapses "
        "FROM flashcards WHERE id = ?",
        (fid,),
    ).fetchone()
    conn.close()
    return dict(r) if r else None


def _revlog_count(fid):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    n = conn.execute("SELECT COUNT(*) FROM flashcard_revlog WHERE flashcard_id = ?", (fid,)).fetchone()[0]
    conn.close()
    return n


# ==================== UNDO BÁSICO ====================


def test_undo_restaura_estado_anterior():
    _novo_flashcard(1, intervalo=5, reps=2, stability=12.3, difficulty=4.5, fsrs_state=2)
    antes = _card_estado(1)

    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.status_code == 200
    depois = _card_estado(1)
    # A revisão realmente mudou o card
    assert depois != antes
    assert _revlog_count(1) == 1

    u = client.post("/api/flashcards/1/undo-review")
    assert u.status_code == 200
    assert u.json()["undone"] is True

    restaurado = _card_estado(1)
    assert restaurado["intervalo_dias"] == antes["intervalo_dias"]
    assert restaurado["proxima_revisao"] == antes["proxima_revisao"]
    assert restaurado["repetitions"] == antes["repetitions"]
    assert restaurado["stability"] == antes["stability"]
    assert restaurado["difficulty"] == antes["difficulty"]
    assert restaurado["fsrs_state"] == antes["fsrs_state"]


def test_undo_apaga_linha_do_revlog():
    _novo_flashcard(1)
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 3})
    assert _revlog_count(1) == 1
    client.post("/api/flashcards/1/undo-review")
    assert _revlog_count(1) == 0


def test_undo_restaura_lapses_apos_again():
    # Again (quality 0 -> rating 1) incrementa lapses; undo deve zerar de volta.
    _novo_flashcard(1, reps=1, fsrs_state=2)
    assert _card_estado(1)["lapses"] == 0
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})
    assert _card_estado(1)["lapses"] == 1
    client.post("/api/flashcards/1/undo-review")
    assert _card_estado(1)["lapses"] == 0


# ==================== UNDO REPETIDO (LIFO) ====================


def test_undo_repetido_desfaz_em_ordem():
    _novo_flashcard(1)
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    apos_1 = _card_estado(1)
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 3})
    assert _revlog_count(1) == 2

    # Desfaz a 2ª revisão → volta ao estado após a 1ª
    client.post("/api/flashcards/1/undo-review")
    assert _revlog_count(1) == 1
    assert _card_estado(1)["intervalo_dias"] == apos_1["intervalo_dias"]
    assert _card_estado(1)["proxima_revisao"] == apos_1["proxima_revisao"]

    # Desfaz a 1ª revisão → revlog vazio
    client.post("/api/flashcards/1/undo-review")
    assert _revlog_count(1) == 0


# ==================== ERROS / EDGE CASES ====================


def test_undo_card_inexistente_404():
    r = client.post("/api/flashcards/99999/undo-review")
    assert r.status_code == 404


def test_undo_sem_revisao_400():
    _novo_flashcard(1)
    r = client.post("/api/flashcards/1/undo-review")
    assert r.status_code == 400


def test_undo_linha_sem_snapshot_400():
    # Simula uma revisão antiga (anterior à migration 80): revlog sem snapshot.
    _novo_flashcard(1)
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcard_revlog "
        "(flashcard_id, user_id, rating, quality, estado_antes, estado_depois, stability, difficulty, "
        " intervalo_dias, elapsed_days, tempo_ms, revisado_em, estado_card_antes) "
        "VALUES (?, ?, 3, 3, 2, 2, 10.0, 4.0, 5, 5, 0, ?, '')",
        (1, _UID, today_str()),
    )
    conn.commit()
    conn.close()
    r = client.post("/api/flashcards/1/undo-review")
    assert r.status_code == 400


def test_undo_nao_vaza_entre_usuarios():
    # Card do user 1; user 2 não deve conseguir desfazer nem enxergar.
    _novo_flashcard(1, uid=_UID)
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert _revlog_count(1) == 1

    async def _uid2():
        return 2

    app.dependency_overrides[get_user_id] = _uid2
    try:
        r = client.post("/api/flashcards/1/undo-review")
        assert r.status_code == 404
    finally:
        app.dependency_overrides[get_user_id] = _override_uid
    # Revlog do dono permanece intacto
    assert _revlog_count(1) == 1

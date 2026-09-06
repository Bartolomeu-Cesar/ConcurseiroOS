"""Testes do preview de intervalos por rating (GET /api/flashcards/{id}/preview-intervalos).

Mostra, para o estado atual do card, o intervalo que cada nota (0-5) produziria — à la
Anki ("Bom +5d") — sem persistir nada.

Cobre:
- Retorna intervalos para todas as 6 notas (0-5), inteiros >= 1.
- Coerência FSRS: Fácil (5) >= Bom (4) >= Difícil (3); notas do mesmo rating FSRS
  produzem o MESMO intervalo (0 e 1 -> Again; 2 e 3 -> Hard).
- NÃO persiste: o estado do card é idêntico antes e depois do preview.
- 404 para card inexistente; isolamento por user_id.

Executar: pytest tests/test_flashcard_preview.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_preview.db", delete=False)
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
    conn.commit()
    conn.close()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def _novo_flashcard(fid, intervalo=5, reps=2, stability=15.0, difficulty=5.0, fsrs_state=2, uid=_UID):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id, stability, difficulty, fsrs_state) "
        "VALUES (?, 'P', 'R', ?, ?, 2.5, ?, ?, ?, ?, ?)",
        (fid, today_str(), intervalo, reps, uid, stability, difficulty, fsrs_state),
    )
    conn.commit()
    conn.close()


def _estado(fid):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    r = conn.execute(
        "SELECT intervalo_dias, proxima_revisao, stability, difficulty, fsrs_state, repetitions FROM flashcards WHERE id = ?",
        (fid,),
    ).fetchone()
    conn.close()
    return dict(r)


# ==================== ESTRUTURA / COERÊNCIA ====================


def test_retorna_intervalos_para_as_6_notas():
    _novo_flashcard(1)
    r = client.get("/api/flashcards/1/preview-intervalos")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == 1
    intervalos = data["intervalos"]
    # JSON serializa chaves int como string; aceita ambos.
    chaves = {str(k) for k in intervalos.keys()}
    assert chaves == {"0", "1", "2", "3", "4", "5"}
    for v in intervalos.values():
        assert isinstance(v, int) and v >= 1


def test_ordem_fsrs_coerente_easy_maior_igual_good_maior_igual_hard():
    _novo_flashcard(1, stability=20.0, fsrs_state=2, reps=3)
    iv = client.get("/api/flashcards/1/preview-intervalos").json()["intervalos"]
    hard = iv[str(3)] if str(3) in iv else iv[3]
    good = iv[str(4)] if str(4) in iv else iv[4]
    easy = iv[str(5)] if str(5) in iv else iv[5]
    assert easy >= good >= hard


def test_notas_do_mesmo_rating_fsrs_tem_mesmo_intervalo():
    # 0 e 1 -> Again; 2 e 3 -> Hard (mapeamento sm2_to_fsrs_rating).
    _novo_flashcard(1)
    iv = client.get("/api/flashcards/1/preview-intervalos").json()["intervalos"]
    g = lambda q: iv[str(q)] if str(q) in iv else iv[q]  # noqa: E731
    assert g(0) == g(1)  # ambos Again
    assert g(2) == g(3)  # ambos Hard


# ==================== NÃO PERSISTE ====================


def test_preview_nao_altera_o_card():
    _novo_flashcard(1, intervalo=5, reps=2, stability=15.0, difficulty=5.0, fsrs_state=2)
    antes = _estado(1)
    client.get("/api/flashcards/1/preview-intervalos")
    client.get("/api/flashcards/1/preview-intervalos")  # duas vezes p/ garantir
    depois = _estado(1)
    assert antes == depois


# ==================== ERROS / ISOLAMENTO ====================


def test_card_inexistente_404():
    r = client.get("/api/flashcards/99999/preview-intervalos")
    assert r.status_code == 404


def test_isolamento_por_usuario():
    _novo_flashcard(1, uid=_UID)

    async def _uid2():
        return 2

    app.dependency_overrides[get_user_id] = _uid2
    try:
        r = client.get("/api/flashcards/1/preview-intervalos")
        assert r.status_code == 404  # user 2 não enxerga o card do user 1
    finally:
        app.dependency_overrides[get_user_id] = _override_uid


def test_card_novo_tambem_preve():
    # Card novo (fsrs_state=0, reps=0): deve prever intervalos sem erro.
    _novo_flashcard(1, intervalo=1, reps=0, stability=0.0, difficulty=0.0, fsrs_state=0)
    r = client.get("/api/flashcards/1/preview-intervalos")
    assert r.status_code == 200
    iv = r.json()["intervalos"]
    assert all((v if isinstance(v, int) else int(v)) >= 1 for v in iv.values())


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

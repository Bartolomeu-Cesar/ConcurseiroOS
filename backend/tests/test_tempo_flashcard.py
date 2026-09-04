"""
Testes do tempo de referência por complexidade dos flashcards
(calcular_tempo_flashcard) e da exposição de `tempo_segundos` no payload de
/api/flashcards/today, usado pelo timer regressivo da revisão (análogo ao das
questões).

Executar: pytest tests/test_tempo_flashcard.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import calcular_tempo_flashcard as calc


# ---------------------------------------------------------------------------
# Unitários da função de tempo
# ---------------------------------------------------------------------------

def test_respeita_faixa_minima_e_maxima():
    """Card minúsculo cai no piso; card gigante cai no teto (10s–120s)."""
    t_min = calc("a", "b", 2)
    assert t_min == 10
    grande = " ".join(["palavra"] * 500)
    t_max = calc(grande, grande, 0)
    assert t_max == 120


def test_texto_maior_aumenta_o_tempo():
    """Perguntas/respostas mais longas devem elevar o tempo."""
    curto = calc("O que é habeas corpus?", "Remédio constitucional.", 2)
    longo = calc(
        " ".join(["conceito"] * 30),
        " ".join(["explicacao"] * 30),
        2,
    )
    assert longo > curto


def test_fator_fsrs_relearning_maior_que_review():
    """Card em relearning (3) exige mais tempo que um maduro em review (2)."""
    p = " ".join(["palavra"] * 15)
    r = " ".join(["resposta"] * 15)
    t_review = calc(p, r, 2)
    t_relearning = calc(p, r, 3)
    t_novo = calc(p, r, 0)
    assert t_relearning > t_review
    assert t_novo > t_review


def test_fsrs_state_none_nao_quebra():
    """fsrs_state None (schemas antigos) usa fallback sem erro."""
    t = calc("pergunta media aqui", "resposta media aqui", None)
    assert 10 <= t <= 120


# ---------------------------------------------------------------------------
# Integração: payload de /api/flashcards/today contém tempo_segundos
# ---------------------------------------------------------------------------

_tmp_db = tempfile.NamedTemporaryFile(suffix="_tempo_flashcard.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app


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


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


def test_today_expoe_tempo_segundos(client):
    """Cada card retornado por /api/flashcards/today deve ter tempo_segundos válido."""
    from utils import today_str

    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM flashcards WHERE 1=1")
    # Card pendente (proxima_revisao <= hoje)
    conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state, user_id) "
        "VALUES ('O que e mandado de seguranca?', 'Remedio constitucional para direito liquido e certo.', ?, 1, 2.5, 0, 'Direito Constitucional', 0, 1)",
        (today_str(),),
    )
    conn.commit()
    conn.close()

    cards = client.get("/api/flashcards/today").json()
    assert len(cards) >= 1
    for c in cards:
        assert "tempo_segundos" in c, "payload do flashcard precisa expor tempo_segundos"
        assert isinstance(c["tempo_segundos"], int)
        assert 10 <= c["tempo_segundos"] <= 120


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

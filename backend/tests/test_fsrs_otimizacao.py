"""Testes da otimização dos pesos FSRS por usuário (#6 do roadmap Anki-like):
- otimizar_pesos_iniciais: estima S0 por rating, monotonicidade, mínimo de amostras.
- review_card(w_inicial=...): S0 customizado altera a stability (retrocompat sem w_inicial).
- Endpoints /fsrs/otimizar e /fsrs/pesos.

Executar: pytest tests/test_fsrs_otimizacao.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fsrs import FSRSCard, W, otimizar_pesos_iniciais, review_card

# ==================== FUNÇÃO PURA ====================


def test_otimiza_com_amostras_suficientes():
    revs = [{"rating": 3, "stability": 5.0} for _ in range(25)]
    revs += [{"rating": 4, "stability": 15.0} for _ in range(25)]
    r = otimizar_pesos_iniciais(revs)
    assert 3 in r["otimizados"]
    assert 4 in r["otimizados"]
    assert abs(r["w_inicial"][3] - 5.0) < 0.01
    assert abs(r["w_inicial"][4] - 15.0) < 0.01


def test_rating_sem_amostras_usa_default():
    revs = [{"rating": 3, "stability": 5.0} for _ in range(25)]
    r = otimizar_pesos_iniciais(revs)
    assert 1 not in r["otimizados"]
    assert r["w_inicial"][1] == W[0]  # default
    assert r["w_inicial"][2] == W[1]


def test_monotonicidade_garantida():
    # Good com S0 alto, Easy com S0 baixo (invertido de propósito)
    revs = [{"rating": 3, "stability": 20.0} for _ in range(25)]
    revs += [{"rating": 4, "stability": 5.0} for _ in range(25)]
    r = otimizar_pesos_iniciais(revs)
    wi = r["w_inicial"]
    assert wi[1] <= wi[2] <= wi[3] <= wi[4], wi  # Easy forçado >= Good


def test_clampa_faixa_sa():
    # Valor absurdo deve ser limitado ao _S0_MAX do rating
    revs = [{"rating": 3, "stability": 9999.0} for _ in range(25)]
    r = otimizar_pesos_iniciais(revs)
    assert r["w_inicial"][3] <= 30.0  # _S0_MAX[3]


def test_sem_dados_nada_otimizado():
    r = otimizar_pesos_iniciais([])
    assert r["otimizados"] == []
    assert r["w_inicial"][3] == W[2]


# ==================== PARAMETRIZAÇÃO DO review_card ====================


def test_review_card_sem_w_inicial_usa_default():
    out = review_card(FSRSCard(), 3)  # Good, card novo
    assert abs(out.stability - W[2]) < 0.01  # S0 default Good


def test_review_card_com_w_inicial_altera_s0():
    out = review_card(FSRSCard(), 3, w_inicial={1: 0.4, 2: 1.2, 3: 10.0, 4: 20.0})
    assert abs(out.stability - 10.0) < 0.01  # usa o S0 customizado


def test_w_inicial_aceita_lista():
    out = review_card(FSRSCard(), 4, w_inicial=[0.4, 1.2, 3.0, 25.0])
    assert abs(out.stability - 25.0) < 0.01


# ==================== ENDPOINTS ====================

_tmp_db = tempfile.NamedTemporaryFile(suffix="_fsrsopt.db", delete=False)
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
    conn.execute("UPDATE metas_config SET fsrs_weights = '' WHERE user_id = ?", (_UID,))
    conn.commit()
    conn.close()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def test_pesos_default_quando_nao_otimizado():
    p = client.get("/api/flashcards/fsrs/pesos").json()
    assert p["otimizado"] is False
    # w_inicial vem com chaves int no default (dict do Python); Good ~ W[2]
    wi = p["w_inicial"]
    good = wi.get(3, wi.get("3"))
    assert abs(float(good) - W[2]) < 0.01


def test_otimizar_sem_historico_falha_gracioso():
    r = client.post("/api/flashcards/fsrs/otimizar").json()
    assert r["ok"] is False
    assert "insuficiente" in r["mensagem"].lower()


def test_otimizar_com_historico_espacado():
    # Insere revlog diretamente com elapsed_days>=1 (revisões espaçadas reais)
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    for i in range(1, 26):
        conn.execute(
            "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, user_id) VALUES (?, 'P', 'R', ?, ?)",
            (i, today_str(), _UID),
        )
        conn.execute(
            "INSERT INTO flashcard_revlog (flashcard_id, user_id, rating, quality, estado_depois, stability, difficulty, intervalo_dias, elapsed_days, revisado_em) "
            "VALUES (?, ?, 3, 4, 2, 6.0, 5.0, 6, 3, ?)",
            (i, _UID, today_str()),
        )
    conn.commit()
    conn.close()

    r = client.post("/api/flashcards/fsrs/otimizar").json()
    assert r["ok"] is True
    assert 3 in r["otimizados"]
    # Consulta reflete o salvo
    p = client.get("/api/flashcards/fsrs/pesos").json()
    assert p["otimizado"] is True


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

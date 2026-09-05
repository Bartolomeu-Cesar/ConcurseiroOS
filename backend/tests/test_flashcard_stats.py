"""Testes do contrato de estatísticas visuais dos flashcards (item #8 do roadmap).

Garante o formato dos dados que a UI de heatmap/forecast consome de
/api/flashcards/retencao-real:
- por_dia: reviews agrupados por dia (últimos 30 dias) com reviews e acertos.
- forecast: cards que vencem por dia nos próximos N dias (a partir de proxima_revisao).

Executar: pytest tests/test_flashcard_stats.py -v
"""

import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_stats.db", delete=False)
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


def _novo_flashcard(fid, intervalo=1, reps=0, stability=0.0, fsrs_state=0, proxima=None):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id, stability, difficulty, fsrs_state, suspenso) "
        "VALUES (?, 'P', 'R', ?, ?, 2.5, ?, ?, ?, 3, ?, 0)",
        (fid, proxima or today_str(), intervalo, reps, _UID, stability, fsrs_state),
    )
    conn.commit()
    conn.close()


def _revlog(fid, rating, dia_iso, elapsed=0):
    """Insere uma linha de revlog num dia específico (para popular por_dia)."""
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcard_revlog "
        "(flashcard_id, user_id, rating, quality, estado_antes, estado_depois, stability, difficulty, "
        " intervalo_dias, elapsed_days, tempo_ms, revisado_em) "
        "VALUES (?, ?, ?, ?, 2, 2, 10.0, 4.0, 5, ?, 0, ?)",
        (fid, _UID, rating, rating, elapsed, f"{dia_iso}T12:00:00+00:00"),
    )
    conn.commit()
    conn.close()


def _sql_now():
    """date('now') do SQLite (UTC) — base p/ datas de forecast, evita mismatch TZ.

    O endpoint compara proxima_revisao com date('now') (UTC do SQLite). Usar
    date.today() do Python (hora local) pode divergir 1 dia perto da meia-noite.
    """
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    hoje = conn.execute("SELECT date('now')").fetchone()[0]
    conn.close()
    return date.fromisoformat(hoje)


def _sql_hoje():
    return _sql_now().isoformat()


def _sql_mais(dias):
    return (_sql_now() + timedelta(days=dias)).isoformat()


# ==================== POR_DIA (heatmap) ====================


def test_por_dia_agrupa_reviews_por_dia():
    _novo_flashcard(1)
    hoje = _sql_hoje()
    ontem = _sql_mais(-1)
    # 2 reviews hoje (1 acerto, 1 erro), 1 review ontem (acerto)
    _revlog(1, 3, hoje)
    _revlog(1, 1, hoje)
    _revlog(1, 4, ontem)

    data = client.get("/api/flashcards/retencao-real").json()
    por_dia = {d["data"]: d for d in data["por_dia"]}
    assert por_dia[hoje]["reviews"] == 2
    assert por_dia[hoje]["acertos"] == 1  # só rating >= 3
    assert por_dia[ontem]["reviews"] == 1
    assert por_dia[ontem]["acertos"] == 1


def test_por_dia_ordenado_e_dentro_de_30_dias():
    _novo_flashcard(1)
    recente = _sql_mais(-3)
    antigo = _sql_mais(-40)  # fora da janela
    _revlog(1, 3, recente)
    _revlog(1, 3, antigo)

    data = client.get("/api/flashcards/retencao-real").json()
    dias = [d["data"] for d in data["por_dia"]]
    assert recente in dias
    assert antigo not in dias  # > 30 dias não entra
    assert dias == sorted(dias)  # ordenado ascendente


def test_por_dia_vazio_sem_reviews():
    _novo_flashcard(1)
    data = client.get("/api/flashcards/retencao-real").json()
    assert data["por_dia"] == []


# ==================== FORECAST (carga futura) ====================


def test_forecast_agrupa_cards_por_vencimento():
    d1 = _sql_mais(1)
    d2 = _sql_mais(2)
    _novo_flashcard(1, proxima=d1)
    _novo_flashcard(2, proxima=d1)
    _novo_flashcard(3, proxima=d2)

    data = client.get("/api/flashcards/retencao-real").json()
    fc = {f["data"]: f["cards"] for f in data["forecast"]}
    assert fc[d1] == 2
    assert fc[d2] == 1


def test_forecast_exclui_suspensos_e_passado():
    hoje = _sql_hoje()
    ontem = _sql_mais(-1)
    futuro = _sql_mais(1)
    _novo_flashcard(1, proxima=futuro)  # entra
    _novo_flashcard(2, proxima=hoje)  # hoje não é > hoje → não entra
    _novo_flashcard(3, proxima=ontem)  # passado → não entra
    # Card suspenso vencendo no futuro → não entra
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id, suspenso) "
        "VALUES (4, 'P', 'R', ?, 1, 2.5, 0, ?, 1)",
        (futuro, _UID),
    )
    conn.commit()
    conn.close()

    data = client.get("/api/flashcards/retencao-real").json()
    fc = {f["data"]: f["cards"] for f in data["forecast"]}
    assert fc.get(futuro) == 1  # só o card 1 (não suspenso)
    assert hoje not in fc
    assert ontem not in fc


def test_forecast_respeita_janela_dias():
    dentro = _sql_mais(5)
    fora = _sql_mais(25)
    _novo_flashcard(1, proxima=dentro)
    _novo_flashcard(2, proxima=fora)

    data = client.get("/api/flashcards/retencao-real?dias_forecast=14").json()
    dias = [f["data"] for f in data["forecast"]]
    assert dentro in dias
    assert fora not in dias  # além dos 14 dias


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

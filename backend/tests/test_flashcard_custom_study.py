"""Testes do Custom Study (filtered deck, à la Anki):
- Modos: errados_hoje, adiantar, materia (cram), leech, dificeis.
- Respeita limite, exclui suspensos (exceto leech), retorna tempo_segundos.
- Validações: modo inválido (400), materia sem materia (400), vazio.

Executar: pytest tests/test_flashcard_custom_study.py -v
"""

import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_customstudy.db", delete=False)
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


def _seed():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM flashcards")
    conn.execute("DELETE FROM flashcard_revlog")
    daqui2 = (date.today() + timedelta(days=2)).isoformat()
    # 1: Dir, difícil, vence hoje
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, materia, user_id, difficulty, fsrs_state) VALUES (1,'P1','R1',?,'Dir',?,8.5,2)",
        (today_str(), _UID),
    )
    # 2: Dir, vence em 2 dias (adiantar)
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, materia, user_id, difficulty) VALUES (2,'P2','R2',?,'Dir',?,2.0)",
        (daqui2, _UID),
    )
    # 3: Port, leech e suspenso
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, materia, user_id, is_leech, lapses, suspenso) VALUES (3,'P3','R3',?,'Port',?,1,9,1)",
        (today_str(), _UID),
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _setup():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_user_id] = _override_uid
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def _cs(modo, **params):
    q = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"/api/flashcards/custom-study?modo={modo}" + (f"&{q}" if q else "")
    return client.get(url)


def test_errados_hoje():
    # Erra o card 1 hoje
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 0})
    data = _cs("errados_hoje").json()
    ids = [c["id"] for c in data["cards"]]
    assert 1 in ids
    assert 3 not in ids  # suspenso não entra


def test_adiantar_pega_proximos_dias():
    data = _cs("adiantar", dias=5).json()
    ids = [c["id"] for c in data["cards"]]
    assert 2 in ids  # vence em 2 dias
    assert 3 not in ids  # suspenso


def test_materia_cram():
    data = _cs("materia", materia="Dir").json()
    ids = {c["id"] for c in data["cards"]}
    assert ids == {1, 2}  # só Dir, não suspensos


def test_materia_sem_materia_400():
    assert _cs("materia").status_code == 400


def test_leech_inclui_suspensos():
    data = _cs("leech").json()
    ids = [c["id"] for c in data["cards"]]
    assert ids == [3]  # o leech (mesmo suspenso) é o alvo


def test_dificeis_ordena_por_difficulty():
    data = _cs("dificeis").json()
    ids = [c["id"] for c in data["cards"]]
    assert ids and ids[0] == 1  # maior difficulty primeiro


def test_modo_invalido_400():
    assert _cs("xyz").status_code == 400


def test_respeita_limite():
    data = _cs("materia", materia="Dir", limite=1).json()
    assert len(data["cards"]) == 1


def test_retorna_tempo_segundos_e_is_leech():
    data = _cs("materia", materia="Dir").json()
    for c in data["cards"]:
        assert "tempo_segundos" in c and isinstance(c["tempo_segundos"], int)
        assert isinstance(c["is_leech"], bool)


def test_vazio_quando_sem_cards():
    # errados_hoje sem ter errado nada
    data = _cs("errados_hoje").json()
    assert data["total"] == 0
    assert data["cards"] == []


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

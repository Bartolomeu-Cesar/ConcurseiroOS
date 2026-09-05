"""Testes do Sibling Burying de flashcards (à la Anki, evolução pós-roadmap).

Ao revisar um card, os cards IRMÃOS (mesmo note_id) que venceriam hoje são adiados
p/ amanhã, para não revisar frente+verso da mesma nota (ou várias oclusões da mesma
imagem) na mesma sessão.

Cobre:
- Revisar um card enterra os irmãos vencidos hoje (proxima_revisao -> amanhã).
- O retorno de review-fsrs traz irmaos_enterrados com a contagem.
- Não afeta cards de OUTRAS notas, nem irmãos já agendados p/ o futuro, nem suspensos.
- Cards sem note_id (ou nota de 1 card só) não enterram nada.
- O agendamento FSRS do irmão (intervalo/stability) não é alterado — só a data.
- Isolamento por user_id.

Executar: pytest tests/test_flashcard_sibling_bury.py -v
"""

import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_sibling.db", delete=False)
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


def _card(fid, note_id=None, proxima=None, intervalo=5, stability=12.0, fsrs_state=2, suspenso=0, uid=_UID):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT INTO flashcards (id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id, stability, difficulty, fsrs_state, note_id, suspenso) "
        "VALUES (?, 'P', 'R', ?, ?, 2.5, 2, ?, ?, 3, ?, ?, ?)",
        (fid, proxima or today_str(), intervalo, uid, stability, fsrs_state, note_id, suspenso),
    )
    conn.commit()
    conn.close()


def _proxima(fid):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    r = conn.execute("SELECT proxima_revisao, intervalo_dias, stability FROM flashcards WHERE id = ?", (fid,)).fetchone()
    conn.close()
    return r


_HOJE = today_str()
_AMANHA = (date.today() + timedelta(days=1)).isoformat()


# ==================== BURYING BÁSICO ====================


def test_revisar_enterra_irmao_vencido_hoje():
    # Nota com 2 cards (frente/verso), ambos vencendo hoje. note_id = 1 (o primeiro).
    _card(1, note_id=1, proxima=_HOJE)
    _card(2, note_id=1, proxima=_HOJE)

    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.status_code == 200
    assert r.json()["irmaos_enterrados"] == 1
    # O irmão (id=2) foi adiado p/ amanhã.
    assert _proxima(2)[0] == _AMANHA


def test_burying_nao_altera_agendamento_fsrs_do_irmao():
    _card(1, note_id=1, proxima=_HOJE, intervalo=5, stability=12.0)
    _card(2, note_id=1, proxima=_HOJE, intervalo=9, stability=30.0)
    client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    prox, intervalo, stab = _proxima(2)
    assert prox == _AMANHA
    # Só a data mudou; intervalo e stability do irmão permanecem.
    assert intervalo == 9
    assert stab == 30.0


def test_enterra_multiplos_irmaos():
    # Nota de imagem com 3 oclusões, todas vencendo hoje.
    for i in (1, 2, 3):
        _card(i, note_id=1, proxima=_HOJE)
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 3})
    assert r.json()["irmaos_enterrados"] == 2
    assert _proxima(2)[0] == _AMANHA
    assert _proxima(3)[0] == _AMANHA


# ==================== NÃO DEVE ENTERRAR ====================


def test_nao_enterra_cards_de_outra_nota():
    _card(1, note_id=1, proxima=_HOJE)
    _card(2, note_id=2, proxima=_HOJE)  # outra nota
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.json()["irmaos_enterrados"] == 0
    assert _proxima(2)[0] == _HOJE  # intacto


def test_nao_enterra_irmao_ja_agendado_futuro():
    futuro = (date.today() + timedelta(days=10)).isoformat()
    _card(1, note_id=1, proxima=_HOJE)
    _card(2, note_id=1, proxima=futuro)  # já no futuro
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.json()["irmaos_enterrados"] == 0
    assert _proxima(2)[0] == futuro  # não mexeu


def test_nao_enterra_irmao_suspenso():
    _card(1, note_id=1, proxima=_HOJE)
    _card(2, note_id=1, proxima=_HOJE, suspenso=1)
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.json()["irmaos_enterrados"] == 0
    assert _proxima(2)[0] == _HOJE


def test_card_sem_note_id_nao_enterra():
    # note_id NULL → card sem nota agrupada.
    _card(1, note_id=None, proxima=_HOJE)
    _card(2, note_id=None, proxima=_HOJE)
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.json()["irmaos_enterrados"] == 0
    assert _proxima(2)[0] == _HOJE


def test_nota_de_um_card_so_nao_enterra():
    _card(1, note_id=1, proxima=_HOJE)  # único card da nota
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.json()["irmaos_enterrados"] == 0


# ==================== ISOLAMENTO ====================


def test_nao_enterra_irmao_de_outro_usuario():
    # Mesmo note_id, mas dono diferente: não pode enterrar entre usuários.
    _card(1, note_id=1, proxima=_HOJE, uid=_UID)
    _card(2, note_id=1, proxima=_HOJE, uid=2)
    r = client.post("/api/flashcards/1/review-fsrs", json={"quality": 4})
    assert r.json()["irmaos_enterrados"] == 0
    assert _proxima(2)[0] == _HOJE


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

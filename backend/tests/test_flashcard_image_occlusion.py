"""Testes do Image Occlusion de flashcards (à la Anki, item #7 do roadmap).

Cobre o endpoint POST /api/flashcards/image-occlusion:
- Cria 1 card por máscara (modo "hide one, show rest"), compartilhando note_id/imagem.
- Cada card guarda oclusao_index (0-based), imagem_data e o JSON de todas as oclusões.
- Validações: imagem obrigatória, data-URI de imagem, ao menos 1 máscara.
- Cards de oclusão entram na fila /today expondo imagem_data/oclusoes/oclusao_index e
  herdam o fluxo FSRS (review-fsrs funciona neles).
- Isolamento por user_id.

Executar: pytest tests/test_flashcard_image_occlusion.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_imgoccl.db", delete=False)
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

# PNG 1x1 transparente como data URI (imagem mínima válida).
PNG_1X1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)


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


_OCL2 = [{"x": 0.1, "y": 0.2, "w": 0.3, "h": 0.1}, {"x": 0.5, "y": 0.6, "w": 0.2, "h": 0.15}]


# ==================== CRIAÇÃO ====================


def test_cria_um_card_por_mascara():
    r = client.post("/api/flashcards/image-occlusion", json={"imagem": PNG_1X1, "oclusoes": _OCL2, "materia": "Anatomia"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["criados"] == 2
    assert data["mascaras"] == 2
    assert len(data["ids"]) == 2


def test_cards_compartilham_note_id_e_imagem():
    r = client.post("/api/flashcards/image-occlusion", json={"imagem": PNG_1X1, "oclusoes": _OCL2})
    ids = r.json()["ids"]
    note_id = r.json()["note_id"]
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    rows = [dict(conn.execute("SELECT note_id, imagem_data, oclusao_index, card_tipo, oclusoes FROM flashcards WHERE id = ?", (i,)).fetchone()) for i in ids]
    conn.close()
    # Mesmo note_id (o primeiro id) e mesma imagem para todos.
    assert all(row["note_id"] == note_id for row in rows)
    assert all(row["imagem_data"] == PNG_1X1 for row in rows)
    assert all(row["card_tipo"] == "oclusao" for row in rows)
    # oclusao_index 0-based, um por card, distintos.
    assert sorted(row["oclusao_index"] for row in rows) == [0, 1]
    # Cada card guarda o JSON com TODAS as máscaras.
    import json

    for row in rows:
        assert len(json.loads(row["oclusoes"])) == 2


def test_oclusoes_como_string_json_tambem_funciona():
    import json

    r = client.post("/api/flashcards/image-occlusion", json={"imagem": PNG_1X1, "oclusoes": json.dumps(_OCL2)})
    assert r.status_code == 200
    assert r.json()["criados"] == 2


# ==================== VALIDAÇÕES ====================


def test_imagem_obrigatoria():
    r = client.post("/api/flashcards/image-occlusion", json={"oclusoes": _OCL2})
    assert r.status_code == 400


def test_imagem_precisa_ser_data_uri():
    r = client.post("/api/flashcards/image-occlusion", json={"imagem": "http://evil/x.png", "oclusoes": _OCL2})
    assert r.status_code == 422


def test_precisa_de_ao_menos_uma_mascara():
    r = client.post("/api/flashcards/image-occlusion", json={"imagem": PNG_1X1, "oclusoes": []})
    assert r.status_code == 400


def test_oclusoes_invalidas_sao_descartadas_e_falha_se_vazio():
    # Retângulos sem dimensão (w/h <= 0) são descartados pelo validador → lista vazia.
    r = client.post(
        "/api/flashcards/image-occlusion",
        json={"imagem": PNG_1X1, "oclusoes": [{"x": 0.1, "y": 0.1, "w": 0, "h": 0}]},
    )
    assert r.status_code == 400


# ==================== INTEGRAÇÃO COM /today E FSRS ====================


def test_cards_oclusao_aparecem_no_today_com_dados():
    client.post("/api/flashcards/image-occlusion", json={"imagem": PNG_1X1, "oclusoes": _OCL2})
    today = client.get("/api/flashcards/today").json()
    oclusao_cards = [c for c in today if c.get("card_tipo") == "oclusao"]
    assert len(oclusao_cards) == 2
    for c in oclusao_cards:
        assert c["imagem_data"] == PNG_1X1
        assert c["oclusao_index"] in (0, 1)
        assert c["oclusoes"]  # JSON não-vazio


def test_card_oclusao_pode_ser_revisado_fsrs():
    ids = client.post("/api/flashcards/image-occlusion", json={"imagem": PNG_1X1, "oclusoes": _OCL2}).json()["ids"]
    r = client.post(f"/api/flashcards/{ids[0]}/review-fsrs", json={"quality": 4})
    assert r.status_code == 200
    # Gravou no revlog (herda o fluxo dos demais cards).
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    n = conn.execute("SELECT COUNT(*) FROM flashcard_revlog WHERE flashcard_id = ?", (ids[0],)).fetchone()[0]
    conn.close()
    assert n == 1


def test_isolamento_por_usuario():
    ids = client.post("/api/flashcards/image-occlusion", json={"imagem": PNG_1X1, "oclusoes": _OCL2}).json()["ids"]

    async def _uid2():
        return 2

    app.dependency_overrides[get_user_id] = _uid2
    try:
        today = client.get("/api/flashcards/today").json()
        assert all(c["id"] not in ids for c in today)
    finally:
        app.dependency_overrides[get_user_id] = _override_uid


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

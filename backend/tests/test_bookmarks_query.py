"""Testes do endpoint GET /api/bookmarks via query string (painel do viewer)."""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_bookmarks_query.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app

PDF = "Materia/arquivo.pdf"


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute("DELETE FROM bookmarks_pdf")
    conn.commit()
    conn.close()
    yield


def _criar(pagina, label="", cor="blue"):
    return client.post("/api/bookmarks", json={"pdf_path": PDF, "pagina": pagina, "label": label, "cor": cor})


def test_listar_por_query():
    _criar(3, "Cap 1")
    _criar(10, "Cap 2")
    r = client.get(f"/api/bookmarks?pdf_path={PDF}")
    assert r.status_code == 200, r.text
    bms = r.json()
    assert len(bms) == 2
    assert [b["pagina"] for b in bms] == [3, 10]  # ordenado por pagina


def test_query_pdf_sem_bookmarks_vazio():
    r = client.get("/api/bookmarks?pdf_path=Outro/x.pdf")
    assert r.status_code == 200
    assert r.json() == []


def test_query_sem_pdf_path_422():
    r = client.get("/api/bookmarks")
    assert r.status_code == 422


def test_excluir_bookmark():
    bid = _criar(5, "del").json()["id"]
    r = client.delete(f"/api/bookmarks/{bid}")
    assert r.status_code == 200
    assert client.get(f"/api/bookmarks?pdf_path={PDF}").json() == []


def test_backward_compat_path_param():
    _criar(1, "compat")
    r = client.get(f"/api/bookmarks/{PDF}")
    assert r.status_code == 200
    assert len(r.json()) == 1

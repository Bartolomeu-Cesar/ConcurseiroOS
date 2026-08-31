"""Testes do endpoint GET /api/pdf-existe/{path} (checagem de existência de PDF)."""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_pdf_existe.db", delete=False)
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
from routers import pdf as pdf_module


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)

# PDF_ROOT temporário com um PDF real.
_pdf_root = tempfile.mkdtemp(prefix="pdfroot_existe_")
Path(_pdf_root, "Materia").mkdir(parents=True, exist_ok=True)
Path(_pdf_root, "Materia", "existe.pdf").write_bytes(b"%PDF-1.4 fake")


@pytest.fixture(autouse=True)
def _ensure(monkeypatch):
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    pdf_module.PDF_ROOT = _pdf_root
    yield


def test_pdf_existente():
    r = client.get("/api/pdf-existe/Materia/existe.pdf")
    assert r.status_code == 200
    assert r.json() == {"existe": True}


def test_pdf_inexistente():
    r = client.get("/api/pdf-existe/Materia/fantasma.pdf")
    assert r.status_code == 200
    assert r.json() == {"existe": False}


def test_pdf_traversal_bloqueado():
    # Traversal deve ser bloqueado — seja por 404 (rota rejeita) ou existe:false.
    r = client.get("/api/pdf-existe/../etc/passwd")
    if r.status_code == 200:
        assert r.json() == {"existe": False}
    else:
        assert r.status_code in (400, 404)


def test_arquivo_nao_pdf():
    Path(_pdf_root, "Materia", "nota.txt").write_bytes(b"nao e pdf")
    r = client.get("/api/pdf-existe/Materia/nota.txt")
    assert r.status_code == 200
    assert r.json() == {"existe": False}

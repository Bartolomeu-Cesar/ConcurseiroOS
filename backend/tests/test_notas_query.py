"""Testes do endpoint GET /api/notas via query string (consumido pelo viewer).

Regressão: o viewer chamava /api/notas?pdf_path=...&pagina=... mas o backend só
tinha /api/notas/{path}, causando "Erro ao carregar notas".
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_notas_query.db", delete=False)
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
    conn.execute("DELETE FROM notas_pdf")
    conn.commit()
    conn.close()
    yield


def _criar(pagina, conteudo):
    return client.post("/api/notas", json={"pdf_path": PDF, "pagina": pagina, "conteudo": conteudo})


def test_listar_por_query_sem_pagina():
    _criar(1, "nota p1")
    _criar(2, "nota p2")
    r = client.get(f"/api/notas?pdf_path={PDF}")
    assert r.status_code == 200, r.text
    notas = r.json()
    assert len(notas) == 2
    assert {n["conteudo"] for n in notas} == {"nota p1", "nota p2"}


def test_listar_por_query_filtrando_pagina():
    _criar(1, "nota p1")
    _criar(2, "nota p2a")
    _criar(2, "nota p2b")
    r = client.get(f"/api/notas?pdf_path={PDF}&pagina=2")
    assert r.status_code == 200
    notas = r.json()
    assert len(notas) == 2
    assert all(n["pagina"] == 2 for n in notas)


def test_query_pdf_sem_notas_retorna_lista_vazia():
    r = client.get("/api/notas?pdf_path=Outro/vazio.pdf")
    assert r.status_code == 200
    assert r.json() == []


def test_query_sem_pdf_path_422():
    # pdf_path é obrigatório na query.
    r = client.get("/api/notas")
    assert r.status_code == 422


def test_backward_compat_path_param():
    """A rota antiga /api/notas/{path} continua funcionando."""
    _criar(1, "compat")
    r = client.get(f"/api/notas/{PDF}")
    assert r.status_code == 200
    assert len(r.json()) == 1

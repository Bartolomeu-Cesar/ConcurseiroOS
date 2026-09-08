"""Regressão: edital favorito de estudos persistido no banco (user_prefs).

GET  /api/config/edital-favorito → {valor, edital_nome, cargo}
PUT  /api/config/edital-favorito → grava "edital|cargo"; vazio limpa (automático)

Antes, o favorito ficava só no localStorage (preso a um navegador). Agora
persiste no banco e sincroniza entre estações.

Base isolada (TEST_DB). Executar: pytest tests/test_edital_favorito.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_favorito.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


def test_favorito_vazio_por_padrao(client):
    r = client.get("/api/config/edital-favorito")
    assert r.status_code == 200
    data = r.json()
    assert data["valor"] == ""
    assert data["edital_nome"] == ""
    assert data["cargo"] == ""


def test_definir_e_ler_favorito(client):
    r = client.put("/api/config/edital-favorito", json={"edital_nome": "TCE-MA 2026", "cargo": "Auditor - Controle Externo"})
    assert r.status_code == 200, r.text
    assert r.json()["valor"] == "TCE-MA 2026|Auditor - Controle Externo"

    r2 = client.get("/api/config/edital-favorito")
    d = r2.json()
    assert d["valor"] == "TCE-MA 2026|Auditor - Controle Externo"
    assert d["edital_nome"] == "TCE-MA 2026"
    assert d["cargo"] == "Auditor - Controle Externo"


def test_atualizar_favorito_sobrescreve(client):
    client.put("/api/config/edital-favorito", json={"edital_nome": "A", "cargo": "X"})
    client.put("/api/config/edital-favorito", json={"edital_nome": "B", "cargo": "Y"})
    d = client.get("/api/config/edital-favorito").json()
    assert d["edital_nome"] == "B" and d["cargo"] == "Y"
    # Não deve duplicar linha (PK user_id+chave).
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        n = c.execute("SELECT COUNT(*) FROM user_prefs WHERE chave='edital_favorito'").fetchone()[0]
        assert n == 1
    finally:
        c.close()


def test_limpar_favorito(client):
    client.put("/api/config/edital-favorito", json={"edital_nome": "TCE-MA", "cargo": "Auditor"})
    r = client.put("/api/config/edital-favorito", json={"edital_nome": "", "cargo": ""})
    assert r.status_code == 200
    assert r.json()["valor"] == ""
    d = client.get("/api/config/edital-favorito").json()
    assert d["valor"] == ""


def test_favorito_sem_cargo(client):
    r = client.put("/api/config/edital-favorito", json={"edital_nome": "Concurso X"})
    assert r.status_code == 200
    d = client.get("/api/config/edital-favorito").json()
    assert d["edital_nome"] == "Concurso X"
    assert d["cargo"] == ""
    assert d["valor"] == "Concurso X|"

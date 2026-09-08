"""Regressão: adicionar disciplina em lote a um cargo (POST /api/edital/lote).

Permite acrescentar uma disciplina (matéria) com vários tópicos de uma vez a um
cargo já importado, sem redigitar concurso/cargo tópico a tópico.

Base isolada (TEST_DB). Executar: pytest tests/test_edital_lote.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_edital_lote.db", delete=False)
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

_UID = 1


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


def _reset():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM edital WHERE user_id = ?", (_UID,))
        c.commit()
    finally:
        c.close()


def _topicos(client, edital, cargo, materia):
    itens = client.get(f"/api/edital?edital_nome={edital}").json()
    itens = itens.get("items", itens) if isinstance(itens, dict) else itens
    return [i["topico"] for i in itens if i["materia"] == materia and (i["cargo"] or "") == cargo]


def test_lote_varios_topicos(client):
    _reset()
    r = client.post("/api/edital/lote", json={
        "edital_nome": "TCE-MA 2026", "cargo": "Auditor - Controle Externo",
        "materia": "Direito Constitucional",
        "topicos": ["Princípios fundamentais", "Direitos e garantias", "Organização do Estado"],
    })
    assert r.status_code == 200, r.text
    assert r.json()["criados"] == 3
    tops = _topicos(client, "TCE-MA 2026", "Auditor - Controle Externo", "Direito Constitucional")
    assert set(tops) == {"Princípios fundamentais", "Direitos e garantias", "Organização do Estado"}


def test_lote_sem_topicos_cria_placeholder(client):
    _reset()
    r = client.post("/api/edital/lote", json={
        "edital_nome": "TCE-MA 2026", "cargo": "Auditor", "materia": "Contabilidade Pública", "topicos": [],
    })
    assert r.status_code == 200, r.text
    assert r.json()["criados"] == 1
    tops = _topicos(client, "TCE-MA 2026", "Auditor", "Contabilidade Pública")
    assert tops == ["(a definir)"]


def test_lote_remove_vazios_e_duplicatas(client):
    _reset()
    r = client.post("/api/edital/lote", json={
        "edital_nome": "C1", "cargo": "X", "materia": "Português",
        "topicos": ["Crase", "  ", "Crase", "Concordância", ""],
    })
    assert r.status_code == 200
    assert r.json()["criados"] == 2  # Crase (dedup) + Concordância
    tops = _topicos(client, "C1", "X", "Português")
    assert sorted(tops) == ["Concordância", "Crase"]


def test_lote_materia_vazia_400(client):
    _reset()
    r = client.post("/api/edital/lote", json={"edital_nome": "C1", "cargo": "X", "materia": "  ", "topicos": ["a"]})
    assert r.status_code == 400


def test_lote_anexa_ao_cargo_existente(client):
    """A disciplina nova deve coexistir com as já importadas no mesmo cargo."""
    _reset()
    # Simula cargo já importado com uma disciplina.
    client.post("/api/edital", json={"edital_nome": "C1", "cargo": "X", "materia": "Existente", "topico": "T1"})
    # Adiciona nova disciplina em lote ao mesmo cargo.
    client.post("/api/edital/lote", json={"edital_nome": "C1", "cargo": "X", "materia": "Nova", "topicos": ["N1", "N2"]})
    itens = client.get("/api/edital?edital_nome=C1").json()
    itens = itens.get("items", itens) if isinstance(itens, dict) else itens
    materias = {i["materia"] for i in itens}
    assert "Existente" in materias and "Nova" in materias

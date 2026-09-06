"""Testes do JOL preditivo (Judgment of Learning) — study_intelligence.

Cobre: registrar previsão, confrontar com resultado (erro de calibração),
resumo agregado (viés overconfidence/underconfidence) e caminhos de erro.

Executar: pytest tests/test_jol_preditivo.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_jol.db", delete=False)
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
    yield
    app.dependency_overrides.pop(get_db_session, None)
    app.dependency_overrides.pop(get_user_id, None)


def test_registrar_jol_ok():
    r = client.post("/api/study-intelligence/jol", json={
        "item_tipo": "topico", "item_ref": "Princípios", "materia": "Dir", "predicao": 80
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["predicao"] == 80
    assert r.json()["id"] > 0


def test_registrar_jol_tipo_invalido_400():
    r = client.post("/api/study-intelligence/jol", json={"item_tipo": "xpto", "predicao": 50})
    assert r.status_code == 400


def test_registrar_jol_sem_predicao_400():
    r = client.post("/api/study-intelligence/jol", json={"item_tipo": "flashcard"})
    assert r.status_code == 400


def test_registrar_jol_clampa_predicao():
    r = client.post("/api/study-intelligence/jol", json={"item_tipo": "questao", "predicao": 150})
    assert r.status_code == 200
    assert r.json()["predicao"] == 100


def test_resolver_jol_boa_calibracao():
    reg = client.post("/api/study-intelligence/jol", json={"item_tipo": "flashcard", "predicao": 90}).json()
    r = client.post(f"/api/study-intelligence/jol/{reg['id']}/resultado", json={"acertou": True})
    assert r.status_code == 200
    b = r.json()
    assert b["resultado"] == 1
    assert b["erro_calibracao"] == 10.0  # |0.9 - 1| * 100


def test_resolver_jol_overconfidence():
    reg = client.post("/api/study-intelligence/jol", json={"item_tipo": "flashcard", "predicao": 85}).json()
    r = client.post(f"/api/study-intelligence/jol/{reg['id']}/resultado", json={"acertou": False})
    assert r.status_code == 200
    assert r.json()["erro_calibracao"] == 85.0
    assert "Overconfidence" in r.json()["feedback"] or "overconfid" in r.json()["feedback"].lower()


def test_resolver_jol_inexistente_404():
    r = client.post("/api/study-intelligence/jol/9999999/resultado", json={"acertou": True})
    assert r.status_code == 404


def test_resolver_jol_sem_acertou_400():
    reg = client.post("/api/study-intelligence/jol", json={"item_tipo": "topico", "predicao": 50}).json()
    r = client.post(f"/api/study-intelligence/jol/{reg['id']}/resultado", json={})
    assert r.status_code == 400


def test_resumo_jol_agrega_e_detecta_vies():
    # Cria um usuário-cenário overconfidence: previsões altas, resultados ruins.
    for _ in range(3):
        reg = client.post("/api/study-intelligence/jol", json={"item_tipo": "questao", "predicao": 90}).json()
        client.post(f"/api/study-intelligence/jol/{reg['id']}/resultado", json={"acertou": False})
    r = client.get("/api/study-intelligence/jol/resumo")
    assert r.status_code == 200
    b = r.json()
    assert b["total_confrontadas"] >= 3
    assert b["erro_medio"] is not None
    # Com previsões 90 e resultados 0, o viés deve ser overconfidence.
    assert b["vies"] == "overconfidence"


def test_resumo_jol_conta_pendentes():
    # Registra sem resolver → deve contar como pendente.
    client.post("/api/study-intelligence/jol", json={"item_tipo": "topico", "predicao": 70})
    r = client.get("/api/study-intelligence/jol/resumo")
    assert r.status_code == 200
    assert r.json()["pendentes"] >= 1

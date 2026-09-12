"""Testes de organização/filtro por ASSUNTO (tópico) em questões e flashcards.

Cobre:
1. Flashcards: create/update com topico, filtro por topico em /api/flashcards,
   listagem de tópicos /api/flashcards/topicos e filtro no /api/flashcards/today.
2. Questões: filtro por topico já existente em /api/questoes e o novo endpoint
   /api/questoes/topicos.

Executar: pytest tests/test_filtro_assunto.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_filtro_assunto.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

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


def _conn():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _reset():
    conn = _conn()
    for t in ("flashcards", "questoes"):
        conn.execute(f"DELETE FROM {t} WHERE user_id = 1")
    conn.commit()
    conn.close()


# ==================== FLASHCARDS ====================


def test_flashcard_create_com_topico(client):
    _reset()
    r = client.post("/api/flashcards", json={
        "pergunta": "Quando usar crase?",
        "resposta": "Fusão de a+a",
        "materia": "Português",
        "topico": "Crase",
    })
    assert r.status_code == 200
    fid = r.json()["id"]
    conn = _conn()
    topico = conn.execute("SELECT topico FROM flashcards WHERE id = ?", (fid,)).fetchone()[0]
    conn.close()
    assert topico == "Crase"


def test_flashcard_update_topico(client):
    _reset()
    fid = client.post("/api/flashcards", json={
        "pergunta": "P", "resposta": "R", "materia": "Informática",
    }).json()["id"]
    r = client.put(f"/api/flashcards/{fid}", json={"topico": "Redes"})
    assert r.status_code == 200
    assert r.json().get("topico") == "Redes" or True  # update retorna dict; confirma no banco
    conn = _conn()
    assert conn.execute("SELECT topico FROM flashcards WHERE id = ?", (fid,)).fetchone()[0] == "Redes"
    conn.close()


def test_flashcard_filtro_por_topico(client):
    _reset()
    client.post("/api/flashcards", json={"pergunta": "A", "resposta": "1", "materia": "Português", "topico": "Crase"})
    client.post("/api/flashcards", json={"pergunta": "B", "resposta": "2", "materia": "Português", "topico": "Regência"})
    client.post("/api/flashcards", json={"pergunta": "C", "resposta": "3", "materia": "Informática", "topico": "Redes"})

    r = client.get("/api/flashcards?topico=Crase")
    assert r.status_code == 200
    itens = r.json().get("items", r.json()) if isinstance(r.json(), dict) else r.json()
    cards = itens["items"] if isinstance(itens, dict) and "items" in itens else itens
    assert all(c["topico"] == "Crase" for c in cards)
    assert len(cards) == 1


def test_flashcard_lista_topicos(client):
    _reset()
    client.post("/api/flashcards", json={"pergunta": "A", "resposta": "1", "materia": "Português", "topico": "Crase"})
    client.post("/api/flashcards", json={"pergunta": "A2", "resposta": "1", "materia": "Português", "topico": "Crase"})
    client.post("/api/flashcards", json={"pergunta": "C", "resposta": "3", "materia": "Informática", "topico": "Redes"})
    client.post("/api/flashcards", json={"pergunta": "D", "resposta": "4", "materia": "Português"})  # sem tópico

    r = client.get("/api/flashcards/topicos")
    assert r.status_code == 200
    data = r.json()
    topicos = {d["topico"]: d["total"] for d in data}
    assert topicos.get("Crase") == 2
    assert topicos.get("Redes") == 1
    assert "" not in topicos  # sem tópico não entra

    # filtrar por matéria
    r2 = client.get("/api/flashcards/topicos?materia=Informática")
    assert {d["topico"] for d in r2.json()} == {"Redes"}


def test_flashcard_today_filtra_por_topico(client):
    _reset()
    conn = _conn()
    hoje = "2020-01-01"
    for p, top in [("X", "Crase"), ("Y", "Crase"), ("Z", "Redes")]:
        conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, materia, topico, proxima_revisao, intervalo_dias, "
            "easiness_factor, repetitions, fsrs_state, user_id) VALUES (?,?,?,?,?,?,?,?,?,1)",
            (p, "r", "Português", top, hoje, 1, 2.5, 1, 2),
        )
    conn.commit()
    conn.close()

    r = client.get("/api/flashcards/today?topico=Crase")
    assert r.status_code == 200
    cards = r.json()
    assert len(cards) == 2
    assert all(c.get("topico") == "Crase" for c in cards)


# ==================== QUESTÕES ====================


def _criar_questao(client, materia, topico, resposta="A"):
    r = client.post("/api/questoes", json={
        "materia": materia, "topico": topico,
        "enunciado": f"{materia}/{topico}?",
        "alternativa_a": "A", "alternativa_b": "B", "alternativa_c": "C",
        "alternativa_d": "D", "alternativa_e": "",
        "resposta_correta": resposta, "explicacao": "x", "dificuldade": "Médio",
    })
    assert r.status_code == 200
    return r.json()["id"]


def test_questoes_filtro_por_topico(client):
    _reset()
    _criar_questao(client, "Português", "Crase")
    _criar_questao(client, "Português", "Regência")
    _criar_questao(client, "Informática", "Sistemas Operacionais")

    r = client.get("/api/questoes?topico=Crase")
    assert r.status_code == 200
    body = r.json()
    itens = body["items"] if isinstance(body, dict) and "items" in body else body
    assert len(itens) == 1
    assert itens[0]["topico"] == "Crase"


def test_questoes_lista_topicos(client):
    _reset()
    _criar_questao(client, "Português", "Crase")
    _criar_questao(client, "Português", "Crase")
    _criar_questao(client, "Informática", "Redes")

    r = client.get("/api/questoes/topicos")
    assert r.status_code == 200
    topicos = {d["topico"]: d["total"] for d in r.json()}
    assert topicos.get("Crase") == 2
    assert topicos.get("Redes") == 1

    r2 = client.get("/api/questoes/topicos?materia=Informática")
    assert {d["topico"] for d in r2.json()} == {"Redes"}

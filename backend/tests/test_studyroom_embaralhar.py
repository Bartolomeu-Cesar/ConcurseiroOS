"""Testes do embaralhamento no fluxo Study Room (Fluxo 2 da seção 11.11).

O Study Room (`pages/studyroom.js`) popula `srQuestoes` via GET /api/questoes?limit=20,
serve cada questão EMBARALHADA sob demanda (GET /api/questoes/{id}?embaralhar=true) e
responde com POST /api/questoes/{id}/responder {embaralhada: true}. Estes testes
exercitam a MESMA sequência de endpoints que o frontend usa, garantindo que:

- A lista de questões (fonte do srQuestoes) retorna itens com id.
- Servir embaralhado + responder a letra exibida acerta e grava a letra ORIGINAL.
- Responder a letra exibida errada erra.

Executar: pytest tests/test_studyroom_embaralhar.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_sr_emb.db", delete=False)
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


def _reset_e_criar(correta="A"):
    textos = {"A": "Texto ALFA", "B": "Texto BETA", "C": "Texto GAMA", "D": "Texto DELTA"}
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM questoes_respostas WHERE user_id = ?", (_UID,))
        c.execute("DELETE FROM questoes WHERE user_id = ?", (_UID,))
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "created_at, user_id) VALUES ('Dir', '', 'Enunciado', ?, ?, ?, ?, '', ?, '', 'Médio', '2026-01-01', ?)",
            (textos["A"], textos["B"], textos["C"], textos["D"], correta, _UID),
        )
        c.commit()
        return cur.lastrowid, textos
    finally:
        c.close()


def _resposta_gravada(qid):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(
            "SELECT resposta_usuario, acertou FROM questoes_respostas WHERE questao_id = ? ORDER BY id DESC LIMIT 1",
            (qid,),
        ).fetchone()
    finally:
        c.close()


def test_lista_questoes_alimenta_srquestoes(client):
    """GET /api/questoes?limit=20 (fonte do srQuestoes) retorna itens com id."""
    qid, _ = _reset_e_criar(correta="A")
    data = client.get("/api/questoes?limit=20").json()
    items = data if isinstance(data, list) else data.get("items", [])
    ids = [it["id"] for it in items]
    assert qid in ids


def test_studyroom_servir_e_responder_acerta(client):
    """Fluxo do Study Room: servir embaralhado + responder a letra exibida acerta."""
    qid, textos = _reset_e_criar(correta="A")
    # Study Room serve embaralhado sob demanda (showSrQuestao)
    q = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    assert q.get("embaralhada") is True
    letra_exibida = q["resposta_correta"]
    assert q[f"alternativa_{letra_exibida.lower()}"] == textos["A"]

    # answerSrQuestao envia embaralhada:true
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": letra_exibida, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is True
    grav = _resposta_gravada(qid)
    assert grav["acertou"] == 1
    assert grav["resposta_usuario"].upper() == "A"  # letra ORIGINAL gravada


def test_studyroom_responder_errada_erra(client):
    qid, _ = _reset_e_criar(correta="A")
    q = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    correta_exibida = q["resposta_correta"]
    outra = next(L for L in ["A", "B", "C", "D"] if L != correta_exibida)
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": outra, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is False


def test_studyroom_seed_por_abertura_valida(client):
    """Modo não-determinístico: serve com seed aleatória e responde enviando a MESMA
    seed (como o showSrQuestao/answerSrQuestao fazem). Valida na ordem exibida."""
    qid, textos = _reset_e_criar(correta="A")
    seed = 424242
    q = client.get(f"/api/questoes/{qid}?embaralhar=true&seed={seed}").json()
    assert q.get("embaralhada") is True
    assert q.get("seed") == seed
    letra_exibida = q["resposta_correta"]
    assert q[f"alternativa_{letra_exibida.lower()}"] == textos["A"]
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": letra_exibida, "embaralhada": True, "seed": seed},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is True
    grav = _resposta_gravada(qid)
    assert grav["resposta_usuario"].upper() == "A"


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

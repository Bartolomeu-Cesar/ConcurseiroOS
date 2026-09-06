"""Testes das 3 melhorias inspiradas no QConcursos:

1. Buscar questão pelo código — GET /api/questoes/codigo/{codigo}
2. Filtros de questões salvos — CRUD /api/questoes/filtros-salvos
3. Questões discursivas — POST /api/questoes/{id}/responder-discursiva + filtro tipo

Executar: pytest tests/test_questoes_melhorias.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_melhorias.db", delete=False)
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


def _criar_objetiva(correta="A"):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "tipo, created_at, user_id) VALUES ('Dir', '', 'Enun', 'a', 'b', 'c', 'd', '', ?, '', 'Médio', "
            "'objetiva', '2026-01-01', ?)",
            (correta, _UID),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def _criar_discursiva(esperada="Resposta modelo esperada"):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "tipo, resposta_esperada, created_at, user_id) VALUES ('Dir', '', 'Disserte sobre X', "
            "'', '', '', '', '', '', '', 'Médio', 'discursiva', ?, '2026-01-01', ?)",
            (esperada, _UID),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


# ============================================================
# Feature 1: buscar questão pelo código
# ============================================================


def test_codigo_numero_puro(client):
    qid = _criar_objetiva()
    r = client.get(f"/api/questoes/codigo/{qid}")
    assert r.status_code == 200
    assert r.json()["id"] == qid


def test_codigo_com_prefixo_Q(client):
    qid = _criar_objetiva()
    r = client.get(f"/api/questoes/codigo/Q{qid}")
    assert r.status_code == 200
    assert r.json()["id"] == qid


def test_codigo_invalido_400(client):
    r = client.get("/api/questoes/codigo/abc")
    assert r.status_code == 400


def test_codigo_inexistente_404(client):
    r = client.get("/api/questoes/codigo/99999999")
    assert r.status_code == 404


# ============================================================
# Feature 2: filtros salvos
# ============================================================


def test_filtro_salvar_listar_excluir(client):
    payload = {"nome": "Meu filtro Dir", "filtros": {"materia": "Direito", "dificuldade": "Difícil"}}
    r = client.post("/api/questoes/filtros-salvos", json=payload)
    assert r.status_code == 200
    fid = r.json()["id"]
    assert r.json()["ok"] is True

    lst = client.get("/api/questoes/filtros-salvos").json()
    achado = next((f for f in lst if f["id"] == fid), None)
    assert achado is not None
    assert achado["nome"] == "Meu filtro Dir"
    assert achado["filtros"]["materia"] == "Direito"

    d = client.delete(f"/api/questoes/filtros-salvos/{fid}")
    assert d.status_code == 200
    lst2 = client.get("/api/questoes/filtros-salvos").json()
    assert all(f["id"] != fid for f in lst2)


def test_filtro_upsert_mesmo_nome(client):
    p1 = {"nome": "Repetido", "filtros": {"banca": "FCC"}}
    r1 = client.post("/api/questoes/filtros-salvos", json=p1)
    id1 = r1.json()["id"]
    assert r1.json()["atualizado"] is False

    p2 = {"nome": "Repetido", "filtros": {"banca": "CESPE"}}
    r2 = client.post("/api/questoes/filtros-salvos", json=p2)
    assert r2.json()["id"] == id1  # mesmo registro
    assert r2.json()["atualizado"] is True

    lst = client.get("/api/questoes/filtros-salvos").json()
    achado = next(f for f in lst if f["id"] == id1)
    assert achado["filtros"]["banca"] == "CESPE"


def test_filtro_nome_vazio_400(client):
    r = client.post("/api/questoes/filtros-salvos", json={"nome": "  ", "filtros": {}})
    assert r.status_code == 400


def test_filtro_excluir_inexistente_404(client):
    r = client.delete("/api/questoes/filtros-salvos/88888888")
    assert r.status_code == 404


# ============================================================
# Feature 3: questões discursivas
# ============================================================


def test_discursiva_responder_com_autoavaliacao_alta(client):
    qid = _criar_discursiva(esperada="O gabarito modelo.")
    r = client.post(
        f"/api/questoes/{qid}/responder-discursiva",
        json={"resposta_texto": "Minha resposta discursiva.", "autoavaliacao": 80, "tempo_segundos": 30},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["acertou"] is True  # >= 60
    assert body["autoavaliacao"] == 80
    assert body["resposta_esperada"] == "O gabarito modelo."


def test_discursiva_autoavaliacao_baixa_erra(client):
    qid = _criar_discursiva()
    r = client.post(
        f"/api/questoes/{qid}/responder-discursiva",
        json={"resposta_texto": "resposta fraca", "autoavaliacao": 40},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is False


def test_discursiva_texto_vazio_400(client):
    qid = _criar_discursiva()
    r = client.post(
        f"/api/questoes/{qid}/responder-discursiva",
        json={"resposta_texto": "   ", "autoavaliacao": 90},
    )
    assert r.status_code == 400


def test_responder_discursiva_em_objetiva_400(client):
    qid = _criar_objetiva()
    r = client.post(
        f"/api/questoes/{qid}/responder-discursiva",
        json={"resposta_texto": "texto", "autoavaliacao": 90},
    )
    assert r.status_code == 400


def test_filtro_tipo_discursiva_no_list(client):
    disc_id = _criar_discursiva()
    _criar_objetiva()
    r = client.get("/api/questoes?tipo=discursiva&limit=200")
    assert r.status_code == 200
    data = r.json()
    itens = data["items"] if isinstance(data, dict) and "items" in data else data
    ids = [q["id"] for q in itens]
    assert disc_id in ids
    # Todos os retornados devem ser discursivos
    assert all(q.get("tipo") == "discursiva" for q in itens)

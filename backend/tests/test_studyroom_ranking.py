"""Testes de salas públicas + ranking/streak persistente do Study Room.

Executar: pytest tests/test_studyroom_ranking.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_sr_ranking.db", delete=False)
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


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


def _insert_studyroom_session(user_id, horas, dias_atras=0):
    """Insere sessão de estudo tipo studyroom para alimentar o ranking."""
    d = (date.today() - timedelta(days=dias_atras)).isoformat()
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute(
            "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES ('Study Room', ?, ?, 'studyroom', ?)",
            (horas, d, user_id),
        )
        c.commit()
    finally:
        c.close()


# ── Salas públicas ──────────────────────────────────────────────────────────
def test_criar_sala_publica_flag(client):
    r = client.post("/api/studyroom/criar", json={"titulo": "Pública PF", "publica": True})
    assert r.status_code == 200
    assert r.json()["publica"] is True


def test_criar_sala_privada_por_padrao(client):
    r = client.post("/api/studyroom/criar", json={"titulo": "Privada"})
    assert r.status_code == 200
    assert r.json()["publica"] is False


def test_listar_publicas_mostra_publica_e_oculta_privada(client):
    pub = client.post("/api/studyroom/criar", json={"titulo": "Sala Aberta X", "publica": True}).json()
    priv = client.post("/api/studyroom/criar", json={"titulo": "Sala Secreta Y", "publica": False}).json()
    r = client.get("/api/studyroom/publicas")
    assert r.status_code == 200
    codigos = [s["codigo"] for s in r.json()["salas"]]
    assert pub["codigo"] in codigos
    assert priv["codigo"] not in codigos


def test_publicas_traz_contagem_e_vagas(client):
    room = client.post("/api/studyroom/criar", json={"titulo": "Contagem", "publica": True, "max_participantes": 5}).json()
    r = client.get("/api/studyroom/publicas")
    sala = next(s for s in r.json()["salas"] if s["codigo"] == room["codigo"])
    assert sala["participantes"] >= 1  # criador entrou
    assert sala["vagas"] == sala["max_participantes"] - sala["participantes"]
    assert "criador" in sala


# ── Ranking persistente ─────────────────────────────────────────────────────
def test_ranking_estrutura(client):
    r = client.get("/api/studyroom/ranking")
    assert r.status_code == 200
    b = r.json()
    assert "semana" in b and "all_time" in b and "streak_sala" in b


def test_ranking_agrega_horas(client):
    _insert_studyroom_session(_UID, 2.5, dias_atras=0)
    r = client.get("/api/studyroom/ranking")
    all_time = r.json()["all_time"]
    me = next((x for x in all_time if x["is_me"]), None)
    assert me is not None
    assert me["horas"] >= 2.5


def test_ranking_streak_conta_dias_consecutivos(client):
    # Sessões hoje, ontem e anteontem → streak >= 3.
    for d in (0, 1, 2):
        _insert_studyroom_session(_UID, 1.0, dias_atras=d)
    r = client.get("/api/studyroom/ranking")
    assert r.json()["streak_sala"] >= 3


def test_ranking_semana_filtra_por_data(client):
    # Sessão de 30 dias atrás não deve contar na semana (mas conta no all-time).
    _insert_studyroom_session(_UID, 5.0, dias_atras=30)
    r = client.get("/api/studyroom/ranking")
    inicio = r.json()["inicio_semana"]
    limite = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    assert inicio == limite

"""Testes do Boss Battle (flashcards gamificados) — Fase 1.

Cobre:
- (B) O payload de /boss-battle inclui a `resposta` de cada card (elimina o
  fetch de todos os flashcards ao revelar).
- (A) O resultado da batalha persiste o XP bônus na tabela boss_battles e esse
  bônus é refletido no XP semanal das Ligas (categoria 'boss_battles'), sem
  duplicar o XP por card (que já entra via streaks.flashcards_revisados).

AUTH_ENABLED=false → user_id sempre 1.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_boss.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session
import settings as settings_mod

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
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


app.dependency_overrides[get_db_session] = _override_db_session


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


def _conn():
    c = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _criar_flashcard_pendente(pergunta, resposta, materia="Geral"):
    """Cria um flashcard com revisão vencida (pendente hoje)."""
    conn = _conn()
    ontem = (date.today() - timedelta(days=1)).isoformat()
    conn.execute(
        """INSERT INTO flashcards (pergunta, resposta, materia, proxima_revisao,
           intervalo_dias, easiness_factor, repetitions, difficulty, stability, fsrs_state, user_id)
           VALUES (?, ?, ?, ?, 1, 2.5, 0, 5.0, 1.0, 0, 1)""",
        (pergunta, resposta, materia, ontem),
    )
    conn.commit()
    conn.close()


# ============================================================
# (B) Payload inclui a resposta
# ============================================================

def test_boss_battle_payload_inclui_resposta(client):
    _criar_flashcard_pendente("O que é HTTP?", "HyperText Transfer Protocol", "Informática")
    r = client.get("/api/study-intelligence/boss-battle")
    assert r.status_code == 200
    data = r.json()
    assert data["boss"] is not None
    assert len(data["cards"]) >= 1
    card = next(c for c in data["cards"] if c["pergunta"] == "O que é HTTP?")
    # A resposta deve vir no payload — evita baixar todos os flashcards ao revelar
    assert card["resposta"] == "HyperText Transfer Protocol"


def test_boss_battle_sem_pendentes(client):
    """Sem flashcards pendentes, retorna boss=None e mensagem."""
    # Zera pendências: adia todos os flashcards
    conn = _conn()
    conn.execute("UPDATE flashcards SET proxima_revisao = '2999-01-01' WHERE user_id = 1")
    conn.commit()
    conn.close()
    r = client.get("/api/study-intelligence/boss-battle")
    assert r.status_code == 200
    data = r.json()
    assert data["boss"] is None
    assert data["cards"] == []


# ============================================================
# (A) XP bônus persistido e refletido na liga
# ============================================================

def test_resultado_persiste_xp_bonus(client):
    """Derrotar o boss sem erros com combo persiste o xp_bonus em boss_battles."""
    r = client.post("/api/study-intelligence/boss-battle/resultado", json={
        "boss_tier": 3, "boss_hp_total": 100, "dano_total": 150, "cards_revisados": 5,
        "acertos_easy": 5, "acertos_good": 0, "acertos_hard": 0, "erros_again": 0,
        "derrotou": True,
    })
    assert r.status_code == 200
    data = r.json()
    # bônus = tier*20 (60) + perfect (50) + combo easy>=3 (30) = 140
    assert data["xp_bonus"] == 140
    # xp_ganho exibido = bônus + cards*5 (feedback)
    assert data["xp_ganho"] == 140 + 5 * 5

    # Persistido na tabela boss_battles
    conn = _conn()
    row = conn.execute(
        "SELECT xp_bonus, derrotou, cards_revisados FROM boss_battles WHERE user_id = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    assert row is not None
    assert row["xp_bonus"] == 140
    assert row["derrotou"] == 1
    assert row["cards_revisados"] == 5


def test_resultado_derrota_sem_bonus(client):
    """Não derrotar o boss e ter erros → sem bônus (mas registra a batalha)."""
    r = client.post("/api/study-intelligence/boss-battle/resultado", json={
        "boss_tier": 2, "boss_hp_total": 200, "dano_total": 50, "cards_revisados": 3,
        "acertos_easy": 0, "acertos_good": 1, "acertos_hard": 1, "erros_again": 1,
        "derrotou": False,
    })
    assert r.status_code == 200
    assert r.json()["xp_bonus"] == 0


def test_xp_bonus_reflete_no_weekly_xp(client):
    """O xp_bonus persistido entra no cálculo semanal de XP da liga."""
    from routers.leagues.helpers import calculate_user_weekly_xp

    # Limpa batalhas e registra uma vitória perfeita nesta semana
    conn = _conn()
    conn.execute("DELETE FROM boss_battles WHERE user_id = 1")
    conn.commit()
    conn.close()

    client.post("/api/study-intelligence/boss-battle/resultado", json={
        "boss_tier": 5, "boss_hp_total": 100, "dano_total": 200, "cards_revisados": 4,
        "acertos_easy": 4, "acertos_good": 0, "acertos_hard": 0, "erros_again": 0,
        "derrotou": True,
    })
    # bônus = 5*20 (100) + 50 + 30 = 180

    hoje = date.today()
    week_start = (hoje - timedelta(days=hoje.weekday())).isoformat()
    week_end = (hoje - timedelta(days=hoje.weekday()) + timedelta(days=6)).isoformat()

    conn = _conn()
    xp = calculate_user_weekly_xp(conn, 1, week_start, week_end)
    conn.close()
    assert "boss_battles" in xp["breakdown"]
    assert xp["breakdown"]["boss_battles"] == 180
    assert xp["total"] >= 180

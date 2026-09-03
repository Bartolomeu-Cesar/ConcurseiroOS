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


# ============================================================
# (C) Nova mecânica de dano (não punir o esforço) + combo
# ============================================================

def test_boss_battle_dano_map_nova_escala(client):
    """O dano_map segue a nova escala (10/15/20/25) e traz config de combo."""
    _criar_flashcard_pendente("Nova escala?", "sim", "Informática")
    r = client.get("/api/study-intelligence/boss-battle")
    assert r.status_code == 200
    data = r.json()
    # dano_map vem com chaves string no JSON
    dm = {int(k): v for k, v in data["dano_map"].items()}
    assert dm == {1: 10, 2: 15, 3: 20, 4: 25}
    # Errar (1) não é irrisório perto de dominar (4): razão 2.5x, não 10x
    assert dm[4] / dm[1] == 2.5
    # Config de combo presente
    assert "combo" in data
    assert data["combo"]["inicio"] >= 1
    assert data["combo"]["teto"] >= data["combo"]["bonus_por_acerto"]


def test_resultado_combo_max_gera_bonus(client):
    """combo_max >= 3 concede o bônus de combo de acertos (mesmo sem 'Easy')."""
    conn = _conn()
    conn.execute("DELETE FROM boss_battles WHERE user_id = 1")
    conn.commit()
    conn.close()

    # Vitória com acertos majoritariamente 'Good' (não Easy), combo de 4 seguidos
    r = client.post("/api/study-intelligence/boss-battle/resultado", json={
        "boss_tier": 1, "boss_hp_total": 80, "dano_total": 90, "cards_revisados": 4,
        "acertos_easy": 0, "acertos_good": 4, "acertos_hard": 0, "erros_again": 0,
        "combo_max": 4, "derrotou": True,
    })
    assert r.status_code == 200
    # bônus = tier*20 (20) + precisão (50) + combo (30) = 100
    assert r.json()["xp_bonus"] == 100


def test_resultado_sem_combo_nao_da_bonus_combo(client):
    """combo_max < 3 (e sem Easy) não concede o bônus de combo."""
    r = client.post("/api/study-intelligence/boss-battle/resultado", json={
        "boss_tier": 1, "boss_hp_total": 80, "dano_total": 40, "cards_revisados": 3,
        "acertos_easy": 0, "acertos_good": 2, "acertos_hard": 0, "erros_again": 1,
        "combo_max": 2, "derrotou": False,
    })
    assert r.status_code == 200
    # não derrotou, teve erro, combo < 3 → bônus 0
    assert r.json()["xp_bonus"] == 0


# ============================================================
# (D) Fraquezas do boss por matéria (dano crítico → interleaving)
# ============================================================

def test_boss_battle_traz_fraquezas_e_crit(client):
    """O payload traz fraquezas (subconjunto das matérias dos cards) e crit_mult."""
    # Zera pendências antigas para controlar as matérias da batalha
    conn = _conn()
    conn.execute("UPDATE flashcards SET proxima_revisao = '2999-01-01' WHERE user_id = 1")
    conn.commit()
    conn.close()
    _criar_flashcard_pendente("D-P1", "r", "Português")
    _criar_flashcard_pendente("D-D1", "r", "Direito")
    _criar_flashcard_pendente("D-I1", "r", "Informática")

    r = client.get("/api/study-intelligence/boss-battle")
    assert r.status_code == 200
    data = r.json()
    assert data["boss"] is not None
    fraquezas = data["fraquezas"]
    materias_cards = {c["materia"] for c in data["cards"]}
    # 1–2 fraquezas, todas presentes entre as matérias da batalha
    assert 1 <= len(fraquezas) <= 2
    assert set(fraquezas) <= materias_cards
    assert data["crit_mult"] == 2
    # boss também expõe as fraquezas
    assert data["boss"]["fraquezas"] == fraquezas


def test_boss_battle_marca_ponto_fraco_nos_cards(client):
    """Cards cuja matéria é fraqueza vêm com ponto_fraco=True; os demais False."""
    conn = _conn()
    conn.execute("UPDATE flashcards SET proxima_revisao = '2999-01-01' WHERE user_id = 1")
    conn.commit()
    conn.close()
    _criar_flashcard_pendente("PF-A", "r", "Matéria A")
    _criar_flashcard_pendente("PF-B", "r", "Matéria B")

    data = client.get("/api/study-intelligence/boss-battle").json()
    fraquezas = set(data["fraquezas"])
    for c in data["cards"]:
        assert c["ponto_fraco"] == (c["materia"] in fraquezas)


def test_fraqueza_prioriza_pior_desempenho(client):
    """A matéria com pior % de acerto em questões deve ser escolhida como fraqueza."""
    conn = _conn()
    conn.execute("UPDATE flashcards SET proxima_revisao = '2999-01-01' WHERE user_id = 1")
    # Duas matérias com flashcards pendentes
    conn.commit()
    conn.close()
    _criar_flashcard_pendente("FR-forte", "r", "MatForte")
    _criar_flashcard_pendente("FR-fraca", "r", "MatFraca")

    # Cria questões: MatForte com bom acerto, MatFraca com péssimo acerto
    conn = _conn()
    from datetime import date as _d
    hoje = _d.today().isoformat()
    def _q(materia, acertou, n):
        for _ in range(n):
            cur = conn.execute(
                """INSERT INTO questoes
                   (materia, enunciado, alternativa_a, alternativa_b, alternativa_c,
                    alternativa_d, alternativa_e, resposta_correta, created_at, user_id)
                   VALUES (?, 'e', 'a', 'b', 'c', 'd', 'e', 'A', ?, 1)""",
                (materia, hoje),
            )
            qid = cur.lastrowid
            conn.execute(
                "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, data, user_id) VALUES (?, 'A', ?, ?, 1)",
                (qid, acertou, hoje),
            )
    _q("MatForte", 1, 8)   # 100% acerto
    _q("MatFraca", 0, 8)   # 0% acerto
    conn.commit()
    conn.close()

    data = client.get("/api/study-intelligence/boss-battle").json()
    # Com 2 matérias, n_fraquezas=1 → deve ser a de pior desempenho
    assert "MatFraca" in data["fraquezas"]

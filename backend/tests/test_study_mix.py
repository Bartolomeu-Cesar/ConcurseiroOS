"""Testes do módulo de distribuição adaptativa NOVO vs. REVISÃO (study_mix).

Cobre:
1. Função pura compute_mix(): fase por dias até prova, freio de backlog,
   override do usuário e clamps.
2. zona_por_dias() e allocate() (ajuste ao que existe nos pools).
3. Integração: endpoints GET/POST /api/estudo/mix (config + preview) e o efeito
   no get_flashcards_today (teto de novos adaptativo respeita backlog).

Executar: pytest tests/test_study_mix.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_study_mix.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import study_mix
from study_mix import MixConfig, allocate, compute_mix, zona_por_dias

# ==================== FUNÇÃO PURA: zona_por_dias ====================


def test_zona_sem_data_e_equilibrio():
    zona, pct = zona_por_dias(None)
    assert zona == "equilibrio"
    assert pct == study_mix.FASE_EQUILIBRIO_PCT_NOVOS


def test_zona_longe_da_prova_expansao():
    zona, pct = zona_por_dias(200)
    assert zona == "expansao"
    assert pct == study_mix.FASE_EXPANSAO_PCT_NOVOS


def test_zona_reta_final():
    zona, pct = zona_por_dias(10)
    assert zona == "reta_final"
    assert pct == study_mix.FASE_RETA_FINAL_PCT_NOVOS


def test_zona_consolidacao_e_equilibrio_limites():
    assert zona_por_dias(21)[0] == "consolidacao"
    assert zona_por_dias(59)[0] == "consolidacao"
    assert zona_por_dias(60)[0] == "equilibrio"
    assert zona_por_dias(119)[0] == "equilibrio"
    assert zona_por_dias(120)[0] == "expansao"


# ==================== FUNÇÃO PURA: compute_mix ====================


def test_mix_longe_da_prova_mais_novos_que_perto():
    longe = compute_mix(backlog_revisao=0, dias_ate_prova=300, carga_override=40)
    perto = compute_mix(backlog_revisao=0, dias_ate_prova=10, carga_override=40)
    assert longe.novos > perto.novos
    assert longe.novos + longe.revisao == 40
    assert perto.novos + perto.revisao == 40


def test_mix_backlog_total_zera_novos():
    # backlog >= carga -> 0 novos, mesmo longe da prova
    m = compute_mix(backlog_revisao=40, dias_ate_prova=300, carga_override=40)
    assert m.novos == 0
    assert m.revisao == 40
    assert "backlog_total" in m.zona


def test_mix_backlog_alto_limita_novos():
    # backlog em 70%+ -> teto de 10% de novos
    m = compute_mix(backlog_revisao=30, dias_ate_prova=300, carga_override=40)
    assert m.novos <= round(40 * study_mix.BACKLOG_TETO_NOVOS_PARCIAL)
    assert "backlog_alto" in m.zona


def test_mix_backlog_baixo_nao_limita():
    m = compute_mix(backlog_revisao=5, dias_ate_prova=300, carga_override=40)
    # expansão = 50% novos, backlog baixo não interfere
    assert m.novos == 20


def test_mix_override_usuario_fixa_proporcao():
    cfg = MixConfig(pct_novos_override=0.25, auto_por_prova=True)
    m = compute_mix(backlog_revisao=0, dias_ate_prova=300, config=cfg, carga_override=40)
    assert m.zona == "manual"
    assert m.novos == 10  # 25% de 40


def test_mix_override_carga_diaria():
    cfg = MixConfig(carga_diaria=100)
    m = compute_mix(backlog_revisao=0, dias_ate_prova=90, config=cfg)  # equilíbrio 35%
    assert m.carga == 100
    assert m.novos == 35


def test_mix_auto_prova_desligado_usa_equilibrio():
    cfg = MixConfig(auto_por_prova=False)
    # mesmo com prova em 5 dias, ignora e usa equilíbrio (sem data)
    m = compute_mix(backlog_revisao=0, dias_ate_prova=5, config=cfg, carga_override=40)
    assert m.zona == "equilibrio"
    assert m.novos == round(40 * study_mix.FASE_EQUILIBRIO_PCT_NOVOS)


def test_mix_soma_sempre_igual_carga():
    for dias in (None, 5, 30, 90, 200):
        for backlog in (0, 3, 20, 40, 100):
            m = compute_mix(backlog_revisao=backlog, dias_ate_prova=dias, carga_override=40)
            assert m.novos + m.revisao == 40
            assert 0 <= m.novos <= 40


# ==================== FUNÇÃO PURA: allocate ====================


def test_allocate_respeita_disponiveis():
    m = compute_mix(backlog_revisao=0, dias_ate_prova=300, carga_override=40)  # 20/20
    n_novos, n_rev = allocate(m, disponiveis_novos=5, disponiveis_revisao=100)
    assert n_novos == 5
    # completa a carga com revisão disponível
    assert n_novos + n_rev == 40


def test_allocate_sem_revisao_completa_com_novos():
    m = compute_mix(backlog_revisao=0, dias_ate_prova=10, carga_override=40)  # 2/38
    n_novos, n_rev = allocate(m, disponiveis_novos=100, disponiveis_revisao=0)
    assert n_rev == 0
    assert n_novos == 40  # completa tudo com novos


def test_allocate_nunca_excede_disponiveis():
    m = compute_mix(backlog_revisao=0, dias_ate_prova=90, carga_override=40)
    n_novos, n_rev = allocate(m, disponiveis_novos=3, disponiveis_revisao=4)
    assert n_novos <= 3
    assert n_rev <= 4
    assert n_novos + n_rev <= 40


# ==================== INTEGRAÇÃO (endpoints + flashcards) ====================

import database  # noqa: E402
from database import get_db_session  # noqa: E402

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient  # noqa: E402
from main import app  # noqa: E402


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


def test_endpoint_get_mix_config_default(client):
    r = client.get("/api/estudo/mix")
    assert r.status_code == 200
    data = r.json()
    assert "config" in data and "preview" in data
    # default: automático (0/0/auto)
    assert data["config"]["carga_diaria"] == 0
    assert data["config"]["pct_novos"] == 0
    assert data["config"]["auto_prova"] is True
    # preview traz os dois mixes
    assert "flashcards" in data["preview"]
    assert "questoes" in data["preview"]
    assert data["preview"]["flashcards"]["novos"] + data["preview"]["flashcards"]["revisao"] > 0


def test_endpoint_set_mix_config_persiste_e_preview(client):
    r = client.post("/api/estudo/mix", json={"carga_diaria": 50, "pct_novos": 20, "auto_prova": False})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["config"]["carga_diaria"] == 50
    assert data["config"]["pct_novos"] == 20
    assert data["config"]["auto_prova"] is False
    # preview reflete pct fixo 20% de 50 = 10 novos
    assert data["preview"]["flashcards"]["novos"] == 10

    # GET confirma persistência
    r2 = client.get("/api/estudo/mix")
    assert r2.json()["config"]["carga_diaria"] == 50
    assert r2.json()["config"]["pct_novos"] == 20

    # limpa (volta ao automático) para não vazar entre testes
    client.post("/api/estudo/mix", json={"carga_diaria": 0, "pct_novos": 0, "auto_prova": True})


def test_endpoint_set_mix_config_validacao(client):
    # pct fora de 0..100
    assert client.post("/api/estudo/mix", json={"pct_novos": 150}).status_code == 400
    # carga fora do intervalo permitido (e != 0)
    assert client.post("/api/estudo/mix", json={"carga_diaria": 1}).status_code == 400
    assert client.post("/api/estudo/mix", json={"carga_diaria": 99999}).status_code == 400


def test_flashcards_today_respeita_teto_de_novos_com_backlog(client):
    # Cenário: muitos cards NOVOS + config que zera novos (pct fixo 0 é automático,
    # então usamos backlog alto criando revisões vencidas). Verifica que o teto de
    # novos cai quando há backlog >= carga.
    conn = _conn()
    conn.execute("DELETE FROM flashcards WHERE user_id = 1")
    hoje = "2020-01-01"  # data no passado => tudo vencido
    # 30 cards de revisão vencidos (fsrs_state=2, repetitions>0)
    for i in range(30):
        conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, materia, proxima_revisao, intervalo_dias, "
            "easiness_factor, repetitions, fsrs_state, user_id) VALUES (?,?,?,?,?,?,?,?,1)",
            (f"R{i}", f"a{i}", "Portugues", hoje, 5, 2.5, 3, 2),
        )
    # 30 cards NOVOS (fsrs_state=0, repetitions=0), também "vencidos" p/ aparecer
    for i in range(30):
        conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, materia, proxima_revisao, intervalo_dias, "
            "easiness_factor, repetitions, fsrs_state, user_id) VALUES (?,?,?,?,?,?,?,?,1)",
            (f"N{i}", f"b{i}", "Portugues", hoje, 0, 2.5, 0, 0),
        )
    # Força carga diária = 20 (backlog de 30 revisões >= carga => 0 novos)
    conn.execute("UPDATE metas_config SET mix_carga_diaria = 20, mix_pct_novos = 0, mix_auto_prova = 1 WHERE user_id = 1")
    conn.commit()
    conn.close()

    r = client.get("/api/flashcards/today")
    assert r.status_code == 200
    cards = r.json()
    # Com backlog total, nenhum card NOVO (todos os retornados são de revisão)
    novos_retornados = [c for c in cards if c["pergunta"].startswith("N")]
    assert novos_retornados == [], f"Não deveria haver novos com backlog total, veio {len(novos_retornados)}"
    # E deve haver revisões
    assert any(c["pergunta"].startswith("R") for c in cards)


def test_flashcards_today_max_novos_explicito_tem_prioridade(client):
    # Se o cliente passa max_novos explicitamente, respeita (override/compat).
    conn = _conn()
    conn.execute("DELETE FROM flashcards WHERE user_id = 1")
    hoje = "2020-01-01"
    for i in range(10):
        conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, materia, proxima_revisao, intervalo_dias, "
            "easiness_factor, repetitions, fsrs_state, user_id) VALUES (?,?,?,?,?,?,?,?,1)",
            (f"N{i}", f"b{i}", "Portugues", hoje, 0, 2.5, 0, 0),
        )
    conn.commit()
    conn.close()

    r = client.get("/api/flashcards/today?max_novos=3")
    assert r.status_code == 200
    cards = r.json()
    novos = [c for c in cards if c["pergunta"].startswith("N")]
    assert len(novos) == 3

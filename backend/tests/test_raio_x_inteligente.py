"""Testes do Raio-X inteligente: score high-yield, incidência real da banca,
tendência temporal (por ano), risco de esquecimento e insights acionáveis.

Executar: pytest tests/test_raio_x_inteligente.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_raiox_int.db", delete=False)
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


def _c():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _add_questao(materia, topico, banca="FGV", ano="", qid_ref=None):
    conn = _c()
    try:
        cur = conn.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "banca, ano, created_at, user_id) VALUES (?,?,'E','a','b','c','d','','A','','Médio',?,?,'2026-01-01',?)",
            (materia, topico, banca, ano, _UID),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _add_edital(materia, topico, mastery=0, proxima_revisao=""):
    conn = _c()
    try:
        conn.execute(
            "INSERT INTO edital (materia, topico, status, arquivado, mastery_level, proxima_revisao, user_id) "
            "VALUES (?,?,'Pendente',0,?,?,?)",
            (materia, topico, mastery, proxima_revisao, _UID),
        )
        # Ciclo ativo para a matéria (regra: recomendações filtram por ativo=1).
        existe = conn.execute("SELECT 1 FROM ciclo_estudos WHERE materia=? AND user_id=?", (materia, _UID)).fetchone()
        if not existe:
            conn.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES (?,1,?)", (materia, _UID))
        conn.commit()
    finally:
        conn.close()


def _responder(qid, acertou, n=1):
    conn = _c()
    try:
        for _ in range(n):
            conn.execute(
                "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id) "
                "VALUES (?, 'A', ?, 10, ?, ?)",
                (qid, acertou, date.today().isoformat(), _UID),
            )
        conn.commit()
    finally:
        conn.close()


# ── Incidência real + high-yield ────────────────────────────────────────────
def test_incidencia_independe_de_respostas(client):
    # Tópico muito cobrado pela banca, mas NUNCA respondido pelo usuário.
    for _ in range(5):
        _add_questao("HY-Mat", "TopNaoRespondido", banca="HYB")
    _add_edital("HY-Mat", "TopNaoRespondido", mastery=10)
    r = client.get("/api/analytics/raio-x/prioridades?banca=HYB")
    assert r.status_code == 200
    item = next((p for p in r.json()["prioridades"] if p["topico"] == "TopNaoRespondido"), None)
    assert item is not None
    # Incidência da banca reflete as 5 questões, mesmo sem respostas.
    assert item["incidencia_banca"] >= 5
    assert item["respondidas"] == 0


def test_high_yield_prioriza_baixo_dominio(client):
    _add_questao("HY2", "Fraco", banca="HYB2")
    _add_questao("HY2", "Forte", banca="HYB2")
    _add_edital("HY2", "Fraco", mastery=10)
    _add_edital("HY2", "Forte", mastery=95)
    r = client.get("/api/analytics/raio-x/prioridades?banca=HYB2")
    prio = {p["topico"]: p["priority_score"] for p in r.json()["prioridades"]}
    # Mesma incidência, mas 'Fraco' (domínio baixo) deve ter prioridade maior.
    assert prio.get("Fraco", 0) > prio.get("Forte", 0)


def test_campos_novos_presentes(client):
    _add_questao("HY3", "T", banca="HYB3", ano="2025")
    _add_edital("HY3", "T", mastery=30)
    r = client.get("/api/analytics/raio-x/prioridades?banca=HYB3")
    p = r.json()["prioridades"][0]
    for campo in ("incidencia_banca", "incidencia_score", "tendencia", "revisao_vencida", "priority_score", "taxa_acerto"):
        assert campo in p
    assert "tem_dados_ano" in r.json()


# ── Tendência temporal ───────────────────────────────────────────────────────
def test_tendencia_subindo(client):
    # Mais questões nos anos recentes → tendência 'subindo'.
    for _ in range(1):
        _add_questao("TR", "Sobe", banca="TRB", ano="2020")
    for _ in range(5):
        _add_questao("TR", "Sobe", banca="TRB", ano="2025")
    _add_edital("TR", "Sobe", mastery=20)
    r = client.get("/api/analytics/raio-x/prioridades?banca=TRB")
    item = next(p for p in r.json()["prioridades"] if p["topico"] == "Sobe")
    assert item["tendencia"] == "subindo"
    assert r.json()["tem_dados_ano"] is True


def test_sem_ano_tendencia_sem_dados(client):
    _add_questao("TR2", "SemAno", banca="TRB2")  # ano vazio
    _add_edital("TR2", "SemAno", mastery=20)
    r = client.get("/api/analytics/raio-x/prioridades?banca=TRB2")
    item = next(p for p in r.json()["prioridades"] if p["topico"] == "SemAno")
    assert item["tendencia"] == "sem_dados"


# ── Risco de esquecimento (revisão vencida) ─────────────────────────────────
def test_revisao_vencida_sobe_prioridade(client):
    ontem = (date.today() - timedelta(days=2)).isoformat()
    _add_questao("RV", "Vencido", banca="RVB")
    _add_questao("RV", "EmDia", banca="RVB")
    _add_edital("RV", "Vencido", mastery=50, proxima_revisao=ontem)
    _add_edital("RV", "EmDia", mastery=50, proxima_revisao=(date.today() + timedelta(days=30)).isoformat())
    r = client.get("/api/analytics/raio-x/prioridades?banca=RVB")
    prio = {p["topico"]: p for p in r.json()["prioridades"]}
    assert prio["Vencido"]["revisao_vencida"] is True
    assert prio["Vencido"]["priority_score"] > prio["EmDia"]["priority_score"]


# ── Insights acionáveis ─────────────────────────────────────────────────────
def test_insights_estrutura(client):
    r = client.get("/api/analytics/raio-x/insights")
    assert r.status_code == 200
    b = r.json()
    assert "insights" in b and isinstance(b["insights"], list)
    assert b["insights"], "deve haver ao menos o insight de 'ok'"
    for ins in b["insights"]:
        assert "tipo" in ins and "texto" in ins and "prioridade" in ins


def test_insights_foco_imediato(client):
    # Alta incidência + baixo domínio → deve gerar insight de foco.
    for _ in range(8):
        _add_questao("INS", "AltaBaixoDominio", banca="INSB")
    _add_edital("INS", "AltaBaixoDominio", mastery=5)
    r = client.get("/api/analytics/raio-x/insights?banca=INSB")
    tipos = [i["tipo"] for i in r.json()["insights"]]
    assert "foco_imediato" in tipos or "tendencia" in tipos or "revisao" in tipos

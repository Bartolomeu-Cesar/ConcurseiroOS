"""Testes da Trilha de Estudo (routers/trilha/core.py).

Cobre:
- Geração sem tópicos → 400.
- Geração com tópicos → etapas ordenadas, primeira não-concluída = 'atual'.
- Filtro por ciclo ativo (skill rule #2): só matérias do ciclo entram.
- Ordem respeita pré-requisitos (topic_dependencies / knowledge graph).
- Tópicos já 'Concluído' viram etapa 'concluida' e contam no progresso.
- GET /api/trilha retorna a trilha ativa; regenerar desativa a anterior.

AUTH_ENABLED=false → user_id sempre 1 (single-user).
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_trilha.db", delete=False)
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
def _clean_and_override():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    conn = _conn()
    # Limpa tabelas relevantes entre testes
    for tbl in ("trilha_etapas", "trilha", "topic_dependencies", "ciclo_estudos", "edital"):
        try:
            conn.execute(f"DELETE FROM {tbl}")
        except Exception:
            pass
    conn.commit()
    conn.close()
    yield


def _conn():
    c = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _add_topico(conn, materia, topico, status="Não Iniciado"):
    cur = conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, arquivado, user_id) "
        "VALUES ('Geral', '', ?, ?, ?, 0, 1)",
        (materia, topico, status),
    )
    return cur.lastrowid


def _add_ciclo(conn, materia, ordem=0):
    conn.execute(
        "INSERT INTO ciclo_estudos (materia, horas_alvo, ordem, ativo, user_id) VALUES (?, 1.0, ?, 1, 1)",
        (materia, ordem),
    )


# ============================================================
# TESTES
# ============================================================


def test_gerar_sem_topicos_retorna_400(client):
    r = client.post("/api/trilha/gerar")
    assert r.status_code == 400
    assert "Nenhum tópico" in r.json()["detail"]


def test_get_sem_trilha_retorna_vazio(client):
    r = client.get("/api/trilha")
    assert r.status_code == 200
    data = r.json()
    assert data["trilha"] is None
    assert data["etapas"] == []


def test_gerar_cria_etapas_ordenadas_com_atual(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Português", "Regência")
    _add_topico(conn, "Direito", "Princípios")
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    data = r.json()
    assert data["trilha"] is not None
    assert data["progresso"]["total_etapas"] == 3
    assert data["progresso"]["concluidas"] == 0

    etapas = data["etapas"]
    # Ordens sequenciais 1..3
    assert [e["ordem"] for e in etapas] == [1, 2, 3]
    # Exatamente uma etapa 'atual' (a primeira), demais 'bloqueada'
    assert etapas[0]["status"] == "atual"
    assert etapas[0]["desbloqueada"] == 1
    assert sum(1 for e in etapas if e["status"] == "atual") == 1
    assert etapas[1]["status"] == "bloqueada"
    assert etapas[2]["status"] == "bloqueada"


def test_filtra_por_ciclo_ativo(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    _add_topico(conn, "Direito", "Princípios")
    _add_topico(conn, "Informática", "Redes")  # fora do ciclo
    # Ciclo ativo só com Português e Direito
    _add_ciclo(conn, "Português", 0)
    _add_ciclo(conn, "Direito", 1)
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    materias = {e["materia"] for e in r.json()["etapas"]}
    assert materias == {"Português", "Direito"}
    assert "Informática" not in materias


def test_ordem_respeita_prerequisitos(client):
    conn = _conn()
    # "Avançado" depende de "Básico" → Básico deve vir antes na trilha
    id_basico = _add_topico(conn, "Direito", "Básico")
    id_avancado = _add_topico(conn, "Direito", "Avançado")
    conn.execute(
        "INSERT INTO topic_dependencies (topic_id, depends_on_id, relationship, user_id, created_at) "
        "VALUES (?, ?, 'prerequisite', 1, '2026-01-01')",
        (id_avancado, id_basico),
    )
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    etapas = sorted(r.json()["etapas"], key=lambda e: e["ordem"])
    topicos_ordem = [e["topico"] for e in etapas]
    assert topicos_ordem.index("Básico") < topicos_ordem.index("Avançado")


def test_topico_concluido_conta_no_progresso(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase", status="Concluído")
    _add_topico(conn, "Português", "Regência", status="Não Iniciado")
    conn.commit()
    conn.close()

    r = client.post("/api/trilha/gerar")
    assert r.status_code == 200
    data = r.json()
    assert data["progresso"]["concluidas"] == 1
    assert data["progresso"]["total_etapas"] == 2
    assert data["progresso"]["pct_conclusao"] == 50.0

    etapas = sorted(data["etapas"], key=lambda e: e["ordem"])
    concluida = next(e for e in etapas if e["topico"] == "Crase")
    atual = next(e for e in etapas if e["topico"] == "Regência")
    assert concluida["status"] == "concluida"
    # A primeira não-concluída vira 'atual'
    assert atual["status"] == "atual"


def test_regenerar_desativa_trilha_anterior(client):
    conn = _conn()
    _add_topico(conn, "Português", "Crase")
    conn.commit()
    conn.close()

    r1 = client.post("/api/trilha/gerar")
    id1 = r1.json()["trilha"]["id"]
    r2 = client.post("/api/trilha/gerar")
    id2 = r2.json()["trilha"]["id"]
    assert id2 != id1

    # GET retorna a mais recente e só uma ativa
    r = client.get("/api/trilha")
    assert r.json()["trilha"]["id"] == id2

    conn = _conn()
    ativas = conn.execute("SELECT COUNT(*) FROM trilha WHERE ativo = 1 AND user_id = 1").fetchone()[0]
    conn.close()
    assert ativas == 1

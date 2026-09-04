"""
Testes da correção da discrepância de "questões de hoje".

Antes: o card "Hoje" (via /api/streaks) usava o contador acumulado
streaks.questoes_resolvidas, que também é incrementado por revisões do caderno
de erros (que não gravam em questoes_respostas). Isso divergia do card
"Questões Resolvidas" do dashboard, que conta a tabela real.

Correção (opção A): /api/streaks e /api/metas passam a contar a tabela real
questoes_respostas WHERE data = hoje, batendo com o dashboard.

Executar: pytest tests/test_questoes_hoje_consistencia.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_questoes_hoje.db", delete=False)
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


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


def _conn():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _reset():
    conn = _conn()
    for t in ("questoes_respostas", "streaks", "metas_config"):
        try:
            conn.execute(f"DELETE FROM {t} WHERE 1=1")
        except Exception:
            pass
    conn.commit()
    conn.close()


def test_streaks_e_metas_contam_tabela_real_nao_o_contador(client):
    """Com contador inflado (revisões de caderno), /api/streaks e /api/metas
    devem refletir a tabela real questoes_respostas, não streaks.questoes_resolvidas."""
    from utils import today_str

    _reset()
    hoje = today_str()
    conn = _conn()
    # 3 respostas reais hoje
    for i in range(3):
        conn.execute(
            "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id) "
            "VALUES (?, 'A', 1, 30, ?, 1)",
            (100 + i, hoje),
        )
    # Contador streaks INFLADO para 10 (simula 7 revisões de caderno de erros + 3 respostas)
    conn.execute(
        "INSERT INTO streaks (data, horas_estudadas, questoes_resolvidas, flashcards_revisados, user_id) "
        "VALUES (?, 1.0, 10, 5, 1)",
        (hoje,),
    )
    conn.commit()
    conn.close()

    # /api/streaks deve mostrar 3 (real), não 10 (contador)
    streaks = client.get("/api/streaks").json()
    assert streaks["hoje"]["questoes_resolvidas"] == 3, (
        f"esperado 3 (tabela real), veio {streaks['hoje']['questoes_resolvidas']} (contador inflado?)"
    )

    # /api/metas idem
    metas = client.get("/api/metas").json()
    assert metas["progresso"]["questoes"] == 3, (
        f"esperado 3 (tabela real), veio {metas['progresso']['questoes']}"
    )


def test_sem_atividade_hoje_retorna_zero(client):
    """Sem respostas hoje, ambos retornam 0 mesmo que o contador tenha lixo."""
    from utils import today_str

    _reset()
    hoje = today_str()
    conn = _conn()
    conn.execute(
        "INSERT INTO streaks (data, horas_estudadas, questoes_resolvidas, flashcards_revisados, user_id) "
        "VALUES (?, 0.5, 8, 2, 1)",
        (hoje,),
    )
    conn.commit()
    conn.close()

    assert client.get("/api/streaks").json()["hoje"]["questoes_resolvidas"] == 0
    assert client.get("/api/metas").json()["progresso"]["questoes"] == 0


def test_resumo_diario_conta_tabela_real(client):
    """/api/resumo-diario deve reportar 'questoes' pela tabela real, não pelo
    contador inflado de streaks."""
    from utils import today_str

    _reset()
    hoje = today_str()
    conn = _conn()
    # 4 respostas reais hoje (precisam de questão para o JOIN do resumo)
    for i in range(4):
        conn.execute(
            "INSERT INTO questoes (id, materia, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, resposta_correta, created_at, user_id) "
            "VALUES (?, 'Informática', 'E?', 'A', 'B', 'C', 'D', 'A', ?, 1)",
            (500 + i, hoje),
        )
        conn.execute(
            "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id) "
            "VALUES (?, 'A', 1, 30, ?, 1)",
            (500 + i, hoje),
        )
    # Contador inflado
    conn.execute(
        "INSERT INTO streaks (data, horas_estudadas, questoes_resolvidas, flashcards_revisados, user_id) "
        "VALUES (?, 1.0, 12, 3, 1)",
        (hoje,),
    )
    conn.commit()
    conn.close()

    resumo = client.get("/api/resumo-diario").json()
    assert resumo["questoes"] == 4, (
        f"esperado 4 (tabela real), veio {resumo['questoes']} (contador inflado?)"
    )
    # e o detalhamento também soma 4
    total_detalhes = sum(d["total"] for d in resumo["questoes_detalhes"])
    assert total_detalhes == 4


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

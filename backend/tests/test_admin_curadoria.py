"""
Testes de curadoria do banco de questões (/api/admin/curadoria/*).

Executar: pytest tests/test_admin_curadoria.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_cur.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from deps import get_user_id
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
client = TestClient(app)


def _override_user_id(uid):
    async def override():
        return uid
    return override


def _q(conn, enunciado, materia="Direito"):
    now = datetime.now(timezone.utc).isoformat()
    cur = conn.execute("""
        INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
            alternativa_c, alternativa_d, resposta_correta, created_at, user_id)
        VALUES (?, '', ?, 'a','b','c','d','A', ?, 1)
    """, (materia, enunciado, now))
    return cur.lastrowid


def _resp(conn, qid, acertou):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("""
        INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, data, user_id)
        VALUES (?, 'A', ?, ?, 1)
    """, (qid, 1 if acertou else 0, now))


def _seed():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (1,'Admin','a@t.com','admin',?, 'admin')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (44,'Comum','c@t.com','comum',?, 'user')",
        (now,),
    )
    # Limpa questões de testes anteriores
    conn.execute("DELETE FROM questoes")
    conn.execute("DELETE FROM questoes_respostas")

    # Questão problemática: 6 respostas, 1 acerto (17%)
    qp = _q(conn, "Questao dificil unica ABC")
    for i in range(6):
        _resp(conn, qp, acertou=(i == 0))

    # Questão boa: 6 respostas, 5 acertos (83%)
    qg = _q(conn, "Questao facil XYZ")
    for i in range(6):
        _resp(conn, qg, acertou=(i != 0))

    # Duplicatas: mesmo enunciado 2x
    _q(conn, "ENUNCIADO DUPLICADO IGUAL")
    _q(conn, "ENUNCIADO DUPLICADO IGUAL")

    conn.commit()
    conn.close()
    return qp


_QP = None


@pytest.fixture(autouse=True)
def _ensure():
    global _QP
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    _QP = _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def test_nao_admin_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(44)
    assert client.get("/api/admin/curadoria/problematicas").status_code == 403


def test_problematicas_lista_baixa_taxa():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/curadoria/problematicas?min_respostas=5&max_taxa=0.4")
    assert r.status_code == 200, r.text
    itens = r.json()["itens"]
    enuns = [i["enunciado"] for i in itens]
    assert any("dificil" in e for e in enuns)
    assert not any("facil" in e for e in enuns)  # a fácil (83%) não entra


def test_duplicatas_detectadas():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/admin/curadoria/duplicatas")
    assert r.status_code == 200
    itens = r.json()["itens"]
    assert any(i["qtd"] == 2 and "DUPLICADO" in i["enunciado"] for i in itens)


def test_excluir_questao_e_auditar():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.delete(f"/api/admin/curadoria/questao/{_QP}")
    assert r.status_code == 200
    # Respostas também sumiram
    r2 = client.get("/api/admin/curadoria/problematicas?min_respostas=5&max_taxa=1.0")
    ids = [i["id"] for i in r2.json()["itens"]]
    assert _QP not in ids
    # Auditado
    r3 = client.get("/api/admin/auditoria?acao=questao.excluir")
    assert any(it["acao"] == "questao.excluir" for it in r3.json()["items"])


def test_excluir_questao_inexistente():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.delete("/api/admin/curadoria/questao/999999")
    assert r.status_code == 404

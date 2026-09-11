"""Testes do endpoint /api/questoes/similar (Errorful Learning).

O caderno de erros e o desafio diário usam este endpoint para, após um erro,
oferecer uma questão SIMILAR (mesma matéria/tópico) para teste imediato —
consolidando a correção (Kornell et al. 2009).

Executar: pytest tests/test_questoes_similar.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_similar.db", delete=False)
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


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


def _criar(client, materia, topico="T", correta="A"):
    r = client.post("/api/questoes", json={
        "materia": materia, "topico": topico, "enunciado": f"Enun {materia}",
        "alternativa_a": "a", "alternativa_b": "b", "alternativa_c": "c",
        "alternativa_d": "d", "alternativa_e": "", "resposta_correta": correta,
        "explicacao": "x", "dificuldade": "Médio",
    })
    assert r.status_code == 200
    return r.json()["id"]


def _reset():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    for t in ("questoes", "questoes_respostas"):
        try:
            c.execute(f"DELETE FROM {t} WHERE 1=1")
        except Exception:
            pass
    c.commit()
    c.close()


class TestQuestaoSimilar:
    def test_retorna_similar_mesma_materia(self, client):
        """Retorna outra questão da mesma matéria, excluindo a própria."""
        _reset()
        q1 = _criar(client, "Informática")
        q2 = _criar(client, "Informática")

        data = client.get(f"/api/questoes/similar?materia=Inform%C3%A1tica&excluir_id={q1}").json()
        assert data and data.get("id") == q2, "deve trazer a outra questão da matéria"
        assert data["id"] != q1, "não pode trazer a própria questão"

    def test_prefere_mesmo_topico(self, client):
        """Havendo questão do mesmo tópico, ela é preferida ao fallback de matéria."""
        _reset()
        q1 = _criar(client, "Direito", topico="Constitucional")
        q_mesmo_topico = _criar(client, "Direito", topico="Constitucional")
        _criar(client, "Direito", topico="Administrativo")  # mesma matéria, outro tópico

        data = client.get(
            f"/api/questoes/similar?materia=Direito&topico=Constitucional&excluir_id={q1}"
        ).json()
        assert data.get("id") == q_mesmo_topico, "deve preferir a questão do mesmo tópico"

    def test_sem_similar_retorna_vazio(self, client):
        """Sem outra questão da matéria, retorna objeto vazio (não 404)."""
        _reset()
        q1 = _criar(client, "Solitária")
        data = client.get(f"/api/questoes/similar?materia=Solit%C3%A1ria&excluir_id={q1}").json()
        assert data == {}, "sem candidata, retorna {}"

    def test_exclui_respondidas_hoje(self, client):
        """Questão já respondida hoje não é oferecida como similar (evita repetir)."""
        _reset()
        from utils import today_str

        q1 = _criar(client, "Geografia")
        q2 = _criar(client, "Geografia")
        # Marca q2 como respondida hoje
        c = sqlite3.connect(_tmp_db.name, timeout=10)
        c.execute(
            "INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id) "
            "VALUES (?, 'A', 1, 30, ?, ?)",
            (q2, today_str(), _UID),
        )
        c.commit()
        c.close()

        data = client.get(f"/api/questoes/similar?materia=Geografia&excluir_id={q1}").json()
        # q2 foi respondida hoje → deve retornar vazio (não oferece repetida)
        assert data == {}, "não deve oferecer questão já respondida hoje"


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

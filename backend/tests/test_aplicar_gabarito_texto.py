"""Testes do endpoint POST /api/questoes/aplicar-gabarito-texto.

Aplica gabarito colado em texto plano (formato 'N letra N letra...' em uma ou
várias linhas) às questões de uma prova escolhida.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_gabtexto.db", delete=False)
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


def _seed_prova(prova: str, n_multipla: int = 3, n_ce: int = 2) -> list[int]:
    """Cria questões (múltipla + certo/errado) SEM gabarito para uma prova."""
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    ids = []
    try:
        for i in range(n_multipla):
            cur = c.execute(
                "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
                "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, "
                "dificuldade, prova_origem, created_at, user_id) "
                "VALUES ('Informática','', ?, 'a','b','c','d','e','', '', 'Médio', ?, '2026-01-01', 1)",
                (f"Questão múltipla {i}", prova),
            )
            ids.append(cur.lastrowid)
        for i in range(n_ce):
            cur = c.execute(
                "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
                "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, "
                "dificuldade, prova_origem, created_at, user_id) "
                "VALUES ('Informática','', ?, 'CERTO','ERRADO','','','','', '', 'Médio', ?, '2026-01-01', 1)",
                (f"Item certo/errado {i}", prova),
            )
            ids.append(cur.lastrowid)
        c.commit()
        return ids
    finally:
        c.close()


def _respostas(ids):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        marks = ",".join("?" * len(ids))
        rows = c.execute(
            f"SELECT id, resposta_correta FROM questoes WHERE id IN ({marks}) ORDER BY id", ids
        ).fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        c.close()


class TestAplicarGabaritoTexto:
    def test_aplica_texto_multilinha(self, client):
        ids = _seed_prova("PROVA_MULTILINHA")  # 3 múltipla + 2 c/e = 5 questões
        # Gabarito em texto plano, múltiplos pares por linha
        texto = "Respostas:\n1 A 2 B 3 C\n4 A 5 B"
        r = client.post(
            "/api/questoes/aplicar-gabarito-texto",
            json={"gabarito_texto": texto, "prova_origem": "PROVA_MULTILINHA"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["aplicadas"] == 5
        resp = _respostas(ids)
        vals = [resp[i] for i in ids]
        # múltiplas: A, B, C ; certo/errado: A (Certo), B (Errado) → 'A','B' diretos
        assert vals == ["A", "B", "C", "A", "B"]

    def test_prova_inexistente_404(self, client):
        r = client.post(
            "/api/questoes/aplicar-gabarito-texto",
            json={"gabarito_texto": "1 A 2 B 3 C", "prova_origem": "NAO_EXISTE"},
        )
        assert r.status_code == 404

    def test_texto_vazio_400(self, client):
        _seed_prova("PROVA_VAZIA")
        r = client.post(
            "/api/questoes/aplicar-gabarito-texto",
            json={"gabarito_texto": "   ", "prova_origem": "PROVA_VAZIA"},
        )
        assert r.status_code == 400

    def test_texto_sem_pares_validos_400(self, client):
        _seed_prova("PROVA_SEM_PARES")
        r = client.post(
            "/api/questoes/aplicar-gabarito-texto",
            json={"gabarito_texto": "isto não é um gabarito", "prova_origem": "PROVA_SEM_PARES"},
        )
        assert r.status_code == 400

    def test_anulacao_x(self, client):
        ids = _seed_prova("PROVA_ANULA", n_multipla=3, n_ce=0)
        r = client.post(
            "/api/questoes/aplicar-gabarito-texto",
            json={"gabarito_texto": "1 A 2 X 3 C", "prova_origem": "PROVA_ANULA"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["anuladas"] == 1
        assert data["aplicadas"] == 2
        resp = _respostas(ids)
        assert resp[ids[0]] == "A"
        assert resp[ids[1]] == ""  # anulada
        assert resp[ids[2]] == "C"

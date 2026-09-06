"""Testes do embaralhamento de alternativas no Daily Challenge (Fluxo 1 da seção 11.11).

O endpoint GET /api/daily-challenge agora serve a questão com alternativas
EMBARALHADAS (mesma semente determinística por user+questão que os demais fluxos).
O frontend (responderDailyChallenge) envia `embaralhada:true` ao responder, e o
backend reaplica o embaralhamento para validar na ordem exibida.

Garante:
- A questão retornada vem com `embaralhada: true` (quando tem > 2 alternativas).
- Servir + responder são CONSISTENTES: escolher a letra do gabarito exibido acerta.
- A letra GRAVADA em resposta_usuario é a ORIGINAL (via mapeamento determinístico).
- Determinismo: duas chamadas ao endpoint remapeiam o gabarito da MESMA forma.

Executar: pytest tests/test_daily_challenge_embaralhar.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_daily_emb.db", delete=False)
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


def _reset_e_criar_uma_questao(correta="A"):
    """Zera questões/respostas e cria UMA questão de 4 alternativas distintas.

    Como o daily-challenge sorteia uma questão NÃO respondida hoje, manter apenas
    uma questão torna o teste determinístico (sempre retorna essa).
    Retorna (id, textos_por_letra).
    """
    textos = {"A": "Texto ALFA", "B": "Texto BETA", "C": "Texto GAMA", "D": "Texto DELTA"}
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM questoes_respostas WHERE user_id = ?", (_UID,))
        c.execute("DELETE FROM questoes WHERE user_id = ?", (_UID,))
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "created_at, user_id) VALUES ('Dir', '', 'Enunciado', ?, ?, ?, ?, '', ?, '', 'Médio', '2026-01-01', ?)",
            (textos["A"], textos["B"], textos["C"], textos["D"], correta, _UID),
        )
        c.commit()
        return cur.lastrowid, textos
    finally:
        c.close()


def _resposta_gravada(qid):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    c.row_factory = sqlite3.Row
    try:
        return c.execute(
            "SELECT resposta_usuario, acertou FROM questoes_respostas WHERE questao_id = ? ORDER BY id DESC LIMIT 1",
            (qid,),
        ).fetchone()
    finally:
        c.close()


def test_daily_challenge_serve_embaralhado(client):
    qid, textos = _reset_e_criar_uma_questao(correta="A")
    d = client.get("/api/daily-challenge").json()
    q = d["questao"]
    assert q["id"] == qid
    assert q.get("embaralhada") is True
    # O gabarito exibido deve apontar para o TEXTO da alternativa A original.
    letra_exibida = q["resposta_correta"]
    assert q[f"alternativa_{letra_exibida.lower()}"] == textos["A"]


def test_daily_challenge_responder_letra_exibida_acerta(client):
    qid, _ = _reset_e_criar_uma_questao(correta="A")
    q = client.get("/api/daily-challenge").json()["questao"]
    letra_exibida = q["resposta_correta"]

    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": letra_exibida, "tempo_segundos": 15, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is True
    # A letra gravada deve ser a ORIGINAL ('A'), traduzida via mapeamento.
    grav = _resposta_gravada(qid)
    assert grav["acertou"] == 1
    assert grav["resposta_usuario"].upper() == "A"


def test_daily_challenge_responder_letra_errada_erra(client):
    qid, _ = _reset_e_criar_uma_questao(correta="A")
    q = client.get("/api/daily-challenge").json()["questao"]
    letra_exibida_correta = q["resposta_correta"]
    outra = next(L for L in ["A", "B", "C", "D"] if L != letra_exibida_correta)

    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": outra, "tempo_segundos": 15, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is False


def test_daily_challenge_determinismo(client):
    """Duas chamadas ao endpoint devem remapear o gabarito para a MESMA letra."""
    qid, _ = _reset_e_criar_uma_questao(correta="B")
    q1 = client.get("/api/daily-challenge").json()["questao"]
    q2 = client.get("/api/daily-challenge").json()["questao"]
    assert q1["resposta_correta"] == q2["resposta_correta"]
    assert q1["alternativa_a"] == q2["alternativa_a"]


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

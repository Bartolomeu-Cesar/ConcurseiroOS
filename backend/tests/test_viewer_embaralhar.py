"""Testes do embaralhamento no fluxo Viewer/PDF (Fluxo 3 da seção 11.11).

No viewer (`pages/viewer.js`), o painel lateral de questões busca a lista, sorteia 5
e serve cada uma EMBARALHADA (GET /api/questoes/{id}?embaralhar=true). O elemento
guarda `data-correct = resposta_correta` (já na ordem EXIBIDA) e `data-embaralhada`.
A correção é client-side (compara a letra clicada com data-correct) E envia ao backend
POST /api/questoes/{id}/responder {embaralhada: true}.

Invariante crítico validado aqui:
- data-correct (resposta_correta embaralhada) aponta para o TEXTO originalmente correto.
- Responder essa letra (embaralhada:true) acerta e grava a letra ORIGINAL.
- Questão Certo/Errado (2 alternativas) NÃO embaralha (embaralhada=false).

Executar: pytest tests/test_viewer_embaralhar.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_viewer_emb.db", delete=False)
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


def _reset_e_criar_4alt(correta="A"):
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


def _criar_certo_errado(correta="A"):
    """Questão de 2 alternativas (Certo/Errado): não deve embaralhar."""
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "created_at, user_id) VALUES ('Dir', '', 'Enunciado CE', 'Certo', 'Errado', '', '', '', ?, '', 'Médio', '2026-01-01', ?)",
            (correta, _UID),
        )
        c.commit()
        return cur.lastrowid
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


def test_viewer_data_correct_aponta_para_texto_correto(client):
    """data-correct (resposta_correta embaralhada) deve apontar para o TEXTO certo."""
    qid, textos = _reset_e_criar_4alt(correta="A")
    q = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    assert q.get("embaralhada") is True
    data_correct = q["resposta_correta"]  # é o que o viewer grava em data-correct
    assert q[f"alternativa_{data_correct.lower()}"] == textos["A"]


def test_viewer_responder_data_correct_acerta(client):
    """Clicar na letra data-correct + enviar embaralhada:true acerta e grava original."""
    qid, _ = _reset_e_criar_4alt(correta="A")
    q = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    data_correct = q["resposta_correta"]
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": data_correct, "tempo_segundos": 20, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is True
    grav = _resposta_gravada(qid)
    assert grav["acertou"] == 1
    assert grav["resposta_usuario"].upper() == "A"


def test_viewer_letra_diferente_do_data_correct_erra(client):
    qid, _ = _reset_e_criar_4alt(correta="A")
    q = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    data_correct = q["resposta_correta"]
    outra = next(L for L in ["A", "B", "C", "D"] if L != data_correct)
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": outra, "tempo_segundos": 20, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is False


def test_viewer_certo_errado_nao_embaralha(client):
    """Questão de 2 alternativas não embaralha (data-embaralhada fica vazio no viewer)."""
    qid = _criar_certo_errado(correta="A")
    q = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    assert q.get("embaralhada") is False
    # resposta_correta permanece a original e responder sem flag (data-embaralhada="") acerta
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": "A", "tempo_segundos": 5, "embaralhada": False},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is True


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

"""Testes da ativação do embaralhamento de alternativas (Opção A).

Fluxo: servir a questão com GET /api/questoes/{id}?embaralhar=true e responder com
POST /api/questoes/{id}/responder {embaralhada: true}. O backend reaplica o
embaralhamento determinístico (mesma semente user+questão) para validar a resposta
NA ORDEM QUE O USUÁRIO VIU e traduzir a letra escolhida de volta para a original.

Garante:
- Servir e responder são CONSISTENTES: escolher a letra do gabarito exibido acerta.
- Escolher outra letra erra.
- A letra GRAVADA em resposta_usuario é a ORIGINAL (via mapeamento).
- Retrocompatível: sem a flag, valida contra a ordem original (comportamento antigo).

Executar: pytest tests/test_questao_embaralhar_responder.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_emb_resp.db", delete=False)
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


def _criar_questao_4alt(correta="A"):
    """Cria questão com 4 alternativas de textos distintos; retorna (id, textos_por_letra)."""
    textos = {
        "A": "Texto ALFA",
        "B": "Texto BETA",
        "C": "Texto GAMA",
        "D": "Texto DELTA",
    }
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
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
        r = c.execute(
            "SELECT resposta_usuario, acertou FROM questoes_respostas WHERE questao_id = ? ORDER BY id DESC LIMIT 1",
            (qid,),
        ).fetchone()
        return r
    finally:
        c.close()


def test_servir_embaralhado_remapeia_gabarito(client):
    qid, textos = _criar_questao_4alt(correta="A")
    d = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    assert d.get("embaralhada") is True
    # A letra correta exibida deve apontar para o TEXTO da alternativa A original.
    letra_correta_exibida = d["resposta_correta"]
    texto_correto_exibido = d[f"alternativa_{letra_correta_exibida.lower()}"]
    assert texto_correto_exibido == textos["A"]  # o gabarito continua sendo o texto certo


def test_responder_embaralhado_letra_exibida_acerta(client):
    qid, textos = _criar_questao_4alt(correta="A")
    d = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    letra_exibida = d["resposta_correta"]  # letra do gabarito NA ORDEM EXIBIDA

    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": letra_exibida, "tempo_segundos": 15, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is True
    # A letra gravada deve ser a ORIGINAL ('A'), não a exibida (via mapeamento).
    grav = _resposta_gravada(qid)
    assert grav["acertou"] == 1
    assert grav["resposta_usuario"].upper() == "A"


def test_responder_embaralhado_letra_errada_erra(client):
    qid, textos = _criar_questao_4alt(correta="A")
    d = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    letra_exibida_correta = d["resposta_correta"]
    # Escolhe uma letra exibida DIFERENTE da correta.
    outra = next(L for L in ["A", "B", "C", "D"] if letra_exibida_correta != L)
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": outra, "tempo_segundos": 15, "embaralhada": True},
    )
    assert r.status_code == 200
    assert r.json()["acertou"] is False


def test_retrocompat_sem_flag_valida_ordem_original(client):
    # Sem embaralhada=true, o backend compara com a ordem ORIGINAL do banco.
    qid, _ = _criar_questao_4alt(correta="C")
    r_ok = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "C", "tempo_segundos": 5})
    assert r_ok.json()["acertou"] is True
    r_err = client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 5})
    assert r_err.json()["acertou"] is False


def test_retorno_resposta_correta_reflete_ordem_exibida(client):
    # O 'resposta_correta' retornado ao responder embaralhado deve ser a letra EXIBIDA
    # (para o front destacar a alternativa certa na tela que o usuário viu).
    qid, _ = _criar_questao_4alt(correta="A")
    d = client.get(f"/api/questoes/{qid}?embaralhar=true").json()
    letra_exibida = d["resposta_correta"]
    r = client.post(
        f"/api/questoes/{qid}/responder",
        json={"resposta": letra_exibida, "tempo_segundos": 10, "embaralhada": True},
    ).json()
    assert r["resposta_correta"].upper() == letra_exibida.upper()

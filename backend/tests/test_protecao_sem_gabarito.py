"""Regressão (opção 3): questões OBJETIVAS sem gabarito (resposta_correta vazia)
não podem ser corrigidas e, portanto, NÃO devem ser servidas em nenhum fluxo de
simulado/estudo/desafio. Se fossem, o app "erraria" o aluno numa questão sem
resposta correta.

Cobre os pontos de seleção protegidos:
- GET /api/daily-challenge (misc + estudo)
- GET /api/active-recall/{materia}
- GET /api/simulado-inteligente (fallback aleatório)
- GET /api/simulado-adaptativo
- GET /api/questoes/stats/sem-gabarito (curadoria)
- GET /api/questoes (listagem já excluía por padrão; sem_gabarito=1 mostra)

Base isolada (TEST_DB). Executar: pytest tests/test_protecao_sem_gabarito.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_sem_gab.db", delete=False)
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


def _reset():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM questoes_respostas WHERE user_id = ?", (_UID,))
        c.execute("DELETE FROM questoes WHERE user_id = ?", (_UID,))
        c.commit()
    finally:
        c.close()


def _criar_questao(materia, correta, enunciado="Enunciado de teste suficientemente longo"):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        cur = c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, "
            "tipo, created_at, user_id) VALUES (?, '', ?, 'A opt', 'B opt', 'C opt', 'D opt', '', ?, '', "
            "'Médio', 'objetiva', '2026-01-01', ?)",
            (materia, enunciado, correta, _UID),
        )
        c.commit()
        return cur.lastrowid
    finally:
        c.close()


def test_daily_challenge_ignora_sem_gabarito(client):
    """Com uma questão COM gabarito e várias SEM, o desafio do dia só pode
    retornar a que tem gabarito (as sem gabarito não são corrigíveis)."""
    _reset()
    com = _criar_questao("Informática", "A")
    for _ in range(20):
        _criar_questao("Informática", "")  # sem gabarito

    # Chama várias vezes: nunca deve devolver uma questão sem gabarito.
    for _ in range(15):
        r = client.get("/api/daily-challenge")
        assert r.status_code == 200
        q = r.json().get("questao") or r.json()
        if q and q.get("id"):
            assert q["id"] == com, "daily-challenge serviu questão sem gabarito"


def test_daily_challenge_vazio_quando_so_ha_sem_gabarito(client):
    """Se TODAS as questões estão sem gabarito, o desafio não retorna questão."""
    _reset()
    for _ in range(10):
        _criar_questao("Informática", "")
    r = client.get("/api/daily-challenge")
    assert r.status_code == 200
    q = r.json().get("questao", None) if isinstance(r.json(), dict) else None
    assert q is None, "não deveria servir questão sem gabarito"


def test_active_recall_ignora_sem_gabarito(client):
    """active-recall só devolve questões com gabarito."""
    _reset()
    com = _criar_questao("Redes", "B")
    for _ in range(5):
        _criar_questao("Redes", "")
    r = client.get("/api/active-recall/Redes")
    assert r.status_code == 200
    qs = r.json().get("questoes", [])
    ids = {q["id"] for q in qs}
    assert ids <= {com}, f"active-recall trouxe questão sem gabarito: {ids}"


def test_simulado_inteligente_fallback_sem_gabarito(client):
    """Sem histórico, o simulado inteligente cai no fallback aleatório — que
    também deve excluir questões sem gabarito."""
    _reset()
    com = _criar_questao("Português", "C")
    for _ in range(10):
        _criar_questao("Português", "")
    r = client.get("/api/simulado-inteligente?qtd=10")
    assert r.status_code == 200
    ids = set(r.json().get("questao_ids", []))
    assert ids <= {com}, f"simulado-inteligente incluiu sem gabarito: {ids}"


def test_simulado_adaptativo_ignora_sem_gabarito(client):
    """O simulado adaptativo só seleciona questões com gabarito."""
    _reset()
    com = _criar_questao("Direito", "D")
    for _ in range(10):
        _criar_questao("Direito", "")
    r = client.get("/api/simulado-adaptativo?qtd=10")
    assert r.status_code == 200
    ids = set(r.json().get("questao_ids", []))
    assert ids <= {com}, f"simulado-adaptativo incluiu sem gabarito: {ids}"


def test_stats_sem_gabarito(client):
    """O endpoint de curadoria conta corretamente as objetivas sem gabarito."""
    _reset()
    _criar_questao("Informática", "A")   # com
    _criar_questao("Informática", "")    # sem
    _criar_questao("Informática", "")    # sem
    _criar_questao("Conhecimentos Gerais", "")  # sem
    r = client.get("/api/questoes/stats/sem-gabarito")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3, data
    por = {x["materia"]: x["qtd"] for x in data["por_materia"]}
    assert por.get("Informática") == 2
    assert por.get("Conhecimentos Gerais") == 1


def test_listagem_exclui_por_padrao_e_mostra_com_flag(client):
    """A listagem principal exclui sem gabarito por padrão, mas as expõe com
    sem_gabarito=1 (para a curadoria)."""
    _reset()
    com = _criar_questao("Informática", "A")
    sem = _criar_questao("Informática", "")

    # Padrão: só a com gabarito.
    r = client.get("/api/questoes?materia=Informática&limit=100")
    assert r.status_code == 200
    body = r.json()
    itens = body.get("items", body) if isinstance(body, dict) else body
    ids = {q["id"] for q in itens}
    assert com in ids and sem not in ids, f"listagem padrão não filtrou sem gabarito: {ids}"

    # Curadoria: sem_gabarito=1 traz as vazias.
    r2 = client.get("/api/questoes?materia=Informática&sem_gabarito=1&limit=100")
    assert r2.status_code == 200
    body2 = r2.json()
    itens2 = body2.get("items", body2) if isinstance(body2, dict) else body2
    ids2 = {q["id"] for q in itens2}
    assert sem in ids2, f"sem_gabarito=1 não trouxe as vazias: {ids2}"

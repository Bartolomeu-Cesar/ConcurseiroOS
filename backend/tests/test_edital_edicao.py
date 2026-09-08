"""Regressão: edição do edital.

- PUT /api/edital/{id}: edita o nome do tópico e/ou a matéria de UM item.
- PUT /api/edital/materia/renomear: renomeia a matéria em TODOS os tópicos da
  disciplina e propaga (opcional) para sessoes_estudo, questoes e ciclo_estudos.

Verifica também que a rota literal materia/renomear NÃO é capturada por /{id}
(ordem de rotas correta) e o escopo por edital/cargo.

Base isolada (TEST_DB). Executar: pytest tests/test_edital_edicao.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_edital_edit.db", delete=False)
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
        for tbl in ("edital", "sessoes_estudo", "questoes", "ciclo_estudos"):
            try:
                c.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (_UID,))
            except Exception:
                pass
        c.commit()
    finally:
        c.close()


def _criar_topico(client, materia, topico, edital="C1", cargo="Cargo"):
    r = client.post("/api/edital", json={"edital_nome": edital, "cargo": cargo, "materia": materia, "topico": topico})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_editar_topico(client):
    _reset()
    tid = _criar_topico(client, "Informatica", "Conceitos basicos")
    r = client.put(f"/api/edital/{tid}", json={"topico": "Conceitos básicos de informática"})
    assert r.status_code == 200, r.text
    assert r.json()["topico"] == "Conceitos básicos de informática"
    # Persistiu?
    itens = client.get("/api/edital?edital_nome=C1").json()
    itens = itens.get("items", itens) if isinstance(itens, dict) else itens
    alvo = [i for i in itens if i["id"] == tid][0]
    assert alvo["topico"] == "Conceitos básicos de informática"


def test_editar_materia_de_um_item(client):
    _reset()
    tid = _criar_topico(client, "Portugues", "Crase")
    r = client.put(f"/api/edital/{tid}", json={"materia": "Português"})
    assert r.status_code == 200, r.text
    assert r.json()["materia"] == "Português"


def test_editar_topico_vazio_rejeitado(client):
    _reset()
    tid = _criar_topico(client, "Direito", "Atos administrativos")
    r = client.put(f"/api/edital/{tid}", json={"topico": "   "})
    assert r.status_code == 400


def test_editar_inexistente_404(client):
    _reset()
    r = client.put("/api/edital/99999999", json={"topico": "x"})
    assert r.status_code == 404


def test_renomear_materia_em_todos_os_topicos(client):
    _reset()
    t1 = _criar_topico(client, "Informatica", "Tópico 1")
    t2 = _criar_topico(client, "Informatica", "Tópico 2")
    t3 = _criar_topico(client, "Direito", "Tópico 3")  # outra matéria, não deve mudar

    r = client.put("/api/edital/materia/renomear", json={
        "materia_antiga": "Informatica", "materia_nova": "Informática", "propagar": False,
    })
    assert r.status_code == 200, r.text
    assert r.json()["topicos_afetados"] == 2

    itens = client.get("/api/edital?edital_nome=C1").json()
    itens = itens.get("items", itens) if isinstance(itens, dict) else itens
    by_id = {i["id"]: i["materia"] for i in itens}
    assert by_id[t1] == "Informática"
    assert by_id[t2] == "Informática"
    assert by_id[t3] == "Direito"


def test_renomear_materia_propaga(client):
    _reset()
    _criar_topico(client, "Redes", "Topologia")
    # Cria dado ligado por nome de matéria.
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES ('Redes', 1.0, '2026-01-01', 'edital', ?)", (_UID,))
        c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, dificuldade, tipo, created_at, user_id) "
            "VALUES ('Redes', '', 'Enun', 'A', 'B', 'C', 'D', '', 'A', 'Médio', 'objetiva', '2026-01-01', ?)", (_UID,))
        c.commit()
    finally:
        c.close()

    r = client.put("/api/edital/materia/renomear", json={
        "materia_antiga": "Redes", "materia_nova": "Redes de Computadores", "propagar": True,
    })
    assert r.status_code == 200, r.text
    prop = r.json()["propagados"]
    assert prop.get("sessoes_estudo", 0) >= 1
    assert prop.get("questoes", 0) >= 1

    # Confere a propagação no banco.
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        n_sess = c.execute("SELECT COUNT(*) FROM sessoes_estudo WHERE materia = 'Redes de Computadores' AND user_id = ?", (_UID,)).fetchone()[0]
        n_q = c.execute("SELECT COUNT(*) FROM questoes WHERE materia = 'Redes de Computadores' AND user_id = ?", (_UID,)).fetchone()[0]
        assert n_sess >= 1 and n_q >= 1
    finally:
        c.close()


def test_renomear_materia_inexistente_404(client):
    _reset()
    r = client.put("/api/edital/materia/renomear", json={
        "materia_antiga": "NaoExiste", "materia_nova": "X",
    })
    assert r.status_code == 404


def test_renomear_materia_nome_igual_400(client):
    _reset()
    _criar_topico(client, "Igual", "T")
    r = client.put("/api/edital/materia/renomear", json={
        "materia_antiga": "Igual", "materia_nova": "Igual",
    })
    assert r.status_code == 400


def test_rota_materia_renomear_nao_capturada_por_id(client):
    """A rota literal /api/edital/materia/renomear deve ter precedência sobre
    /api/edital/{id} (senão 'materia' seria interpretado como id inválido)."""
    _reset()
    _criar_topico(client, "AlgumaMateria", "T")
    # Se {id} capturasse, viria 422 (int inválido) ou 404 de tópico; esperamos 200.
    r = client.put("/api/edital/materia/renomear", json={
        "materia_antiga": "AlgumaMateria", "materia_nova": "OutraMateria", "propagar": False,
    })
    assert r.status_code == 200, r.text


def test_rota_arquivar_nao_capturada_por_id(client):
    """A rota literal /api/edital/arquivar não pode ser capturada por /{id:int}
    (regressão: o {id} greedy quebrava o arquivamento com 422)."""
    _reset()
    _criar_topico(client, "MatArq", "T", edital="ConcArq", cargo="CargoArq")
    r = client.put("/api/edital/arquivar", params={"edital_nome": "ConcArq", "cargo": "CargoArq"})
    assert r.status_code == 200, r.text

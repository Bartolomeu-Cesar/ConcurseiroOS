"""Regressão: endpoint neutro PUT /api/materias/renomear (cascata global).

Renomeia uma matéria em TODAS as tabelas da taxonomia (edital, questoes,
flashcards, sessoes_estudo, ciclo_estudos, ...), mantendo os nomes consistentes
entre as telas. Usado tanto pelo banco de questões quanto pelo edital.

Também cobre a delegação do endpoint do edital (PUT /api/edital/materia/renomear
com propagar=True) para o mesmo helper de cascata.

Base isolada (TEST_DB). Executar: pytest tests/test_materias_renomear.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_mat_renomear.db", delete=False)
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
        for tbl in ("edital", "questoes", "flashcards", "sessoes_estudo", "ciclo_estudos"):
            try:
                c.execute(f"DELETE FROM {tbl} WHERE user_id = ?", (_UID,))
            except Exception:
                pass
        c.commit()
    finally:
        c.close()


def _seed_materia(materia):
    """Cria 1 registro da matéria em cada tabela-chave da taxonomia."""
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("INSERT INTO edital (edital_nome, cargo, materia, topico, user_id) VALUES ('C1','Cargo',?, 'T', ?)", (materia, _UID))
        c.execute(
            "INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, "
            "alternativa_c, alternativa_d, alternativa_e, resposta_correta, dificuldade, tipo, created_at, user_id) "
            "VALUES (?, '', 'Enun', 'A', 'B', 'C', 'D', '', 'A', 'Médio', 'objetiva', '2026-01-01', ?)", (materia, _UID))
        c.execute("INSERT INTO flashcards (pergunta, resposta, materia, proxima_revisao, user_id) VALUES ('P','R',?,'2026-01-01',?)", (materia, _UID))
        c.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, 1.0, '2026-01-01', 'edital', ?)", (materia, _UID))
        c.execute("INSERT INTO ciclo_estudos (materia, ativo, user_id) VALUES (?, 1, ?)", (materia, _UID))
        c.commit()
    finally:
        c.close()


def _conta(materia, tabela):
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        return c.execute(f"SELECT COUNT(*) FROM {tabela} WHERE materia = ? AND user_id = ?", (materia, _UID)).fetchone()[0]
    finally:
        c.close()


def test_renomear_cascata_afeta_todas_as_tabelas(client):
    _reset()
    _seed_materia("Informatica")
    r = client.put("/api/materias/renomear", json={"materia_antiga": "Informatica", "materia_nova": "Informática"})
    assert r.status_code == 200, r.text
    data = r.json()
    af = data["afetados"]
    # Todas as 5 tabelas semeadas devem ter sido renomeadas.
    for tbl in ("edital", "questoes", "flashcards", "sessoes_estudo", "ciclo_estudos"):
        assert af.get(tbl, 0) == 1, f"{tbl} não renomeado: {af}"
    assert data["total"] == 5
    # Confere no banco: nome antigo sumiu, novo apareceu.
    for tbl in ("edital", "questoes", "flashcards", "sessoes_estudo", "ciclo_estudos"):
        assert _conta("Informatica", tbl) == 0
        assert _conta("Informática", tbl) == 1


def test_renomear_inexistente_404(client):
    _reset()
    r = client.put("/api/materias/renomear", json={"materia_antiga": "NaoExiste", "materia_nova": "X"})
    assert r.status_code == 404


def test_renomear_nome_igual_400(client):
    _reset()
    _seed_materia("Igual")
    r = client.put("/api/materias/renomear", json={"materia_antiga": "Igual", "materia_nova": "Igual"})
    assert r.status_code == 400


def test_renomear_vazio_400(client):
    _reset()
    r = client.put("/api/materias/renomear", json={"materia_antiga": "  ", "materia_nova": "X"})
    assert r.status_code == 400


def test_edital_renomear_delega_para_cascata(client):
    """O endpoint do edital com propagar=True usa o mesmo helper: renomeia também
    questões/flashcards/sessões/ciclo, não só o edital."""
    _reset()
    _seed_materia("Redes")
    r = client.put("/api/edital/materia/renomear", json={
        "materia_antiga": "Redes", "materia_nova": "Redes de Computadores", "propagar": True,
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["topicos_afetados"] == 1  # tabela edital
    prop = data["propagados"]
    assert prop.get("questoes", 0) == 1
    assert prop.get("flashcards", 0) == 1
    assert prop.get("sessoes_estudo", 0) == 1
    assert prop.get("ciclo_estudos", 0) == 1
    assert "edital" not in prop  # edital é reportado à parte (topicos_afetados)
    assert _conta("Redes de Computadores", "questoes") == 1


def test_edital_renomear_sem_propagar_so_edital(client):
    """propagar=False renomeia SOMENTE na tabela edital."""
    _reset()
    _seed_materia("SoEdital")
    r = client.put("/api/edital/materia/renomear", json={
        "materia_antiga": "SoEdital", "materia_nova": "SoEditalNovo", "propagar": False,
    })
    assert r.status_code == 200, r.text
    assert r.json()["propagados"] == {}
    assert _conta("SoEditalNovo", "edital") == 1
    # Questões e flashcards permanecem com o nome antigo.
    assert _conta("SoEdital", "questoes") == 1
    assert _conta("SoEdital", "flashcards") == 1

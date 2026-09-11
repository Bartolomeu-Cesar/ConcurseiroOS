"""Testes dos mapas mentais do edital (/api/edital/mapa-mental).

Cobre: geração (agrupamento por prefixo numérico, estrutura SVG, código
Mermaid), stats corretos com status canônico Title Case, matéria inexistente,
e a listagem de matérias com mapas disponíveis (>= 3 tópicos).

Executar: pytest tests/test_mapa_mental.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_mapa.db", delete=False)
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


def _conn():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _reset():
    conn = _conn()
    conn.execute("DELETE FROM edital WHERE 1=1")
    conn.commit()
    conn.close()


def _add(materia, topico, status="Não Iniciado"):
    conn = _conn()
    conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, horas_estudadas, arquivado, user_id) "
        "VALUES ('Geral', '', ?, ?, ?, 0, 0, ?)",
        (materia, topico, status, _UID),
    )
    conn.commit()
    conn.close()


class TestGerarMapaMental:
    def test_gera_estrutura_e_stats(self, client):
        _reset()
        _add("Dir Const", "1 Princípios Fundamentais", status="Concluído")
        _add("Dir Const", "1.1 Soberania", status="Em Andamento")
        _add("Dir Const", "2 Direitos e Garantias", status="Não Iniciado")

        data = client.get("/api/edital/mapa-mental?materia=Dir%20Const").json()
        assert data["materia"] == "Dir Const"
        assert data["root"] == "Dir Const"
        # estrutura SVG presente
        assert isinstance(data["grupos"], list) and len(data["grupos"]) >= 1
        # código Mermaid presente
        assert data["mermaid_mindmap"].startswith("mindmap")
        assert "graph TD" in data["mermaid_flowchart"]
        # stats com status canônico Title Case
        s = data["stats"]
        assert s["total"] == 3
        assert s["concluidos"] == 1
        assert s["em_andamento"] == 1, "status 'Em Andamento' (Title Case) deve ser contado"
        assert s["nao_iniciados"] == 1
        assert s["pct_concluido"] == round(1 / 3 * 100, 1)

    def test_agrupa_por_prefixo_numerico(self, client):
        _reset()
        _add("Português", "1 Fonologia")
        _add("Português", "1.1 Encontros")
        _add("Português", "1.2 Sílaba")
        _add("Português", "2 Morfologia")

        data = client.get("/api/edital/mapa-mental?materia=Portugu%C3%AAs").json()
        # grupo "1" tem 3 itens, grupo "2" tem 1
        grupos = data["grupos"]
        tamanhos = sorted(len(g["itens"]) for g in grupos)
        assert tamanhos == [1, 3], f"esperado grupos de 1 e 3 itens, veio {tamanhos}"

    def test_status_em_andamento_recebe_icone_azul(self, client):
        """Regressão: 'Em Andamento' (Title Case) deve gerar ícone 🔵 no mermaid."""
        _reset()
        _add("Info", "1 Redes", status="Em Andamento")
        _add("Info", "2 Segurança", status="Em Andamento")
        data = client.get("/api/edital/mapa-mental?materia=Info").json()
        assert "🔵" in data["mermaid_mindmap"], "Em Andamento deve virar ícone azul"

    def test_materia_inexistente_vazio(self, client):
        _reset()
        data = client.get("/api/edital/mapa-mental?materia=Inexistente").json()
        assert data["mermaid"] == "" and "mensagem" in data


class TestMapasDisponiveis:
    def test_lista_apenas_materias_com_3_ou_mais(self, client):
        _reset()
        for i in range(3):
            _add("ComMapa", f"{i+1} T{i}")
        _add("SemMapa", "1 Único")  # só 1 tópico → não entra

        data = client.get("/api/edital/mapas-mentais-disponiveis").json()
        materias = {m["materia"] for m in data}
        assert "ComMapa" in materias
        assert "SemMapa" not in materias, "matéria com < 3 tópicos não deve aparecer"

    def test_pct_concluido(self, client):
        _reset()
        _add("X", "1 A", status="Concluído")
        _add("X", "2 B", status="Concluído")
        _add("X", "3 C", status="Não Iniciado")
        data = client.get("/api/edital/mapas-mentais-disponiveis").json()
        x = next(m for m in data if m["materia"] == "X")
        assert x["total_topicos"] == 3 and x["concluidos"] == 2
        assert x["pct"] == round(2 / 3 * 100, 1)


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

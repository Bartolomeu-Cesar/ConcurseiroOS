"""Testes do Knowledge Graph (mapa de dependências entre tópicos do edital).

Cobre: CRUD de edges (criar/atualizar/remover, validações e detecção de ciclo),
pré-requisitos recursivos, sugestão automática por heurísticas e a ordem ótima
de estudo (topological sort + scoring + bloqueio por pré-requisito).

Executar: pytest tests/test_knowledge_graph.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_kg.db", delete=False)
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
    for t in ("edital", "topic_dependencies"):
        try:
            conn.execute(f"DELETE FROM {t} WHERE 1=1")
        except Exception:
            pass
    conn.commit()
    conn.close()


def _add_topico(materia, topico, status="Não Iniciado", horas=0.0):
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO edital (edital_nome, cargo, materia, topico, status, horas_estudadas, arquivado, user_id) "
        "VALUES ('Geral', '', ?, ?, ?, ?, 0, ?)",
        (materia, topico, status, horas, _UID),
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return tid


# ============================================================
# 1. CRUD de edges + validações
# ============================================================

class TestEdgesCRUD:
    def test_criar_edge_prerequisite(self, client):
        _reset()
        a = _add_topico("Dir", "Básico")
        b = _add_topico("Dir", "Avançado")
        r = client.post("/api/knowledge-graph/edges", json={
            "topic_id": b, "depends_on_id": a, "relationship": "prerequisite"
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True and r.json()["updated"] is False

        # aparece no grafo
        g = client.get("/api/knowledge-graph").json()
        assert g["stats"]["total_edges"] == 1
        assert any(e["topic_id"] == b and e["depends_on_id"] == a for e in g["edges"])

    def test_auto_dependencia_rejeitada(self, client):
        _reset()
        a = _add_topico("Dir", "Único")
        r = client.post("/api/knowledge-graph/edges", json={"topic_id": a, "depends_on_id": a})
        assert r.status_code == 400

    def test_tipo_invalido_rejeitado(self, client):
        _reset()
        a = _add_topico("Dir", "A"); b = _add_topico("Dir", "B")
        r = client.post("/api/knowledge-graph/edges", json={
            "topic_id": b, "depends_on_id": a, "relationship": "xpto"
        })
        assert r.status_code == 400

    def test_topico_inexistente_404(self, client):
        _reset()
        a = _add_topico("Dir", "A")
        r = client.post("/api/knowledge-graph/edges", json={"topic_id": a, "depends_on_id": 999999})
        assert r.status_code == 404

    def test_duplicata_atualiza(self, client):
        _reset()
        a = _add_topico("Dir", "A"); b = _add_topico("Dir", "B")
        client.post("/api/knowledge-graph/edges", json={"topic_id": b, "depends_on_id": a, "relationship": "prerequisite"})
        r = client.post("/api/knowledge-graph/edges", json={"topic_id": b, "depends_on_id": a, "relationship": "related"})
        assert r.status_code == 200 and r.json()["updated"] is True
        # continua sendo 1 edge (atualizado, não duplicado)
        assert client.get("/api/knowledge-graph").json()["stats"]["total_edges"] == 1

    def test_ciclo_prerequisite_rejeitado(self, client):
        _reset()
        a = _add_topico("Dir", "A"); b = _add_topico("Dir", "B")
        # A depende de B
        client.post("/api/knowledge-graph/edges", json={"topic_id": a, "depends_on_id": b, "relationship": "prerequisite"})
        # B depende de A → ciclo, deve rejeitar
        r = client.post("/api/knowledge-graph/edges", json={"topic_id": b, "depends_on_id": a, "relationship": "prerequisite"})
        assert r.status_code == 400

    def test_remover_edge(self, client):
        _reset()
        a = _add_topico("Dir", "A"); b = _add_topico("Dir", "B")
        eid = client.post("/api/knowledge-graph/edges", json={"topic_id": b, "depends_on_id": a}).json()["id"]
        r = client.delete(f"/api/knowledge-graph/edges/{eid}")
        assert r.status_code == 200
        assert client.get("/api/knowledge-graph").json()["stats"]["total_edges"] == 0


# ============================================================
# 2. Pré-requisitos recursivos
# ============================================================

class TestPrerequisites:
    def test_cadeia_recursiva(self, client):
        _reset()
        a = _add_topico("Dir", "A", status="Concluído")
        b = _add_topico("Dir", "B", status="Concluído")
        c = _add_topico("Dir", "C")
        # C depende de B, B depende de A
        client.post("/api/knowledge-graph/edges", json={"topic_id": c, "depends_on_id": b, "relationship": "prerequisite"})
        client.post("/api/knowledge-graph/edges", json={"topic_id": b, "depends_on_id": a, "relationship": "prerequisite"})

        data = client.get(f"/api/knowledge-graph/prerequisites/{c}").json()
        ids = {p["id"] for p in data["prerequisites"]}
        assert a in ids and b in ids, "deve subir a cadeia recursivamente"
        assert data["all_completed"] is True, "todos os pré-requisitos estão Concluídos"

    def test_all_completed_false_quando_pendente(self, client):
        _reset()
        a = _add_topico("Dir", "A", status="Não Iniciado")
        b = _add_topico("Dir", "B")
        client.post("/api/knowledge-graph/edges", json={"topic_id": b, "depends_on_id": a, "relationship": "prerequisite"})
        data = client.get(f"/api/knowledge-graph/prerequisites/{b}").json()
        assert data["all_completed"] is False


# ============================================================
# 3. Sugestão automática
# ============================================================

class TestSuggest:
    def test_sugere_sequencia_e_basico_avancado(self, client):
        _reset()
        _add_topico("Dir", "Introdução ao Direito")
        _add_topico("Dir", "Princípios Fundamentais")
        _add_topico("Dir", "Tópico Avançado de Direito")

        data = client.get("/api/knowledge-graph/suggest?materia=Dir").json()
        sugs = data["suggestions"]
        assert len(sugs) > 0, "deve sugerir dependências"
        # Deve haver ao menos uma sugestão básico→avançado (confiança alta 0.8)
        assert any(s["reason"].startswith("Padrão nome") for s in sugs)
        # E sugestões de sequência
        assert any(s["reason"] == "Sequência no edital" for s in sugs)
        # ordenadas por confiança desc
        confs = [s["confidence"] for s in sugs]
        assert confs == sorted(confs, reverse=True)

    def test_nao_sugere_duplicata_existente(self, client):
        _reset()
        a = _add_topico("Dir", "Básico")
        b = _add_topico("Dir", "Avançado")
        # cria a dependência avançado→básico
        client.post("/api/knowledge-graph/edges", json={"topic_id": b, "depends_on_id": a, "relationship": "prerequisite"})
        data = client.get("/api/knowledge-graph/suggest?materia=Dir").json()
        # não deve sugerir o par que já existe
        assert not any(s["topic_id"] == b and s["depends_on_id"] == a for s in data["suggestions"])


# ============================================================
# 4. Ordem ótima de estudo (topological sort + scoring + bloqueio)
# ============================================================

class TestOptimalOrder:
    def test_topico_sem_prereq_vem_antes_do_bloqueado(self, client):
        _reset()
        base = _add_topico("Dir", "Base", status="Não Iniciado")
        dependente = _add_topico("Dir", "Dependente", status="Não Iniciado")
        # dependente depende de base (base NÃO concluída) → dependente bloqueado
        client.post("/api/knowledge-graph/edges", json={
            "topic_id": dependente, "depends_on_id": base, "relationship": "prerequisite"
        })

        data = client.get("/api/knowledge-graph/optimal-order?materia=Dir").json()
        ordem = data["ordem"]
        pos = {o["id"]: o["posicao"] for o in ordem}
        assert pos[base] < pos[dependente], "base (sem prereq) vem antes do dependente"

        # dependente deve estar marcado como bloqueado
        item_dep = next(o for o in ordem if o["id"] == dependente)
        assert item_dep.get("bloqueado") is True
        assert data["total_bloqueados"] == 1
        assert data["total_desbloqueados"] == 1

    def test_prereq_concluido_desbloqueia(self, client):
        _reset()
        base = _add_topico("Dir", "Base", status="Concluído")
        dependente = _add_topico("Dir", "Dependente", status="Não Iniciado")
        client.post("/api/knowledge-graph/edges", json={
            "topic_id": dependente, "depends_on_id": base, "relationship": "prerequisite"
        })
        data = client.get("/api/knowledge-graph/optimal-order?materia=Dir").json()
        item_dep = next(o for o in data["ordem"] if o["id"] == dependente)
        assert not item_dep.get("bloqueado"), "prereq concluído desbloqueia o dependente"
        assert data["total_bloqueados"] == 0

    def test_scoring_desbloqueio_prioriza(self, client):
        """Um tópico que desbloqueia outros deve ter score maior (aparecer antes)
        entre os disponíveis."""
        _reset()
        # 'chave' desbloqueia 2 tópicos; 'solto' não desbloqueia ninguém.
        chave = _add_topico("Dir", "Chave", status="Não Iniciado")
        d1 = _add_topico("Dir", "Dep1", status="Concluído")
        d2 = _add_topico("Dir", "Dep2", status="Concluído")
        solto = _add_topico("Dir", "Solto", status="Não Iniciado")
        client.post("/api/knowledge-graph/edges", json={"topic_id": d1, "depends_on_id": chave, "relationship": "prerequisite"})
        client.post("/api/knowledge-graph/edges", json={"topic_id": d2, "depends_on_id": chave, "relationship": "prerequisite"})

        data = client.get("/api/knowledge-graph/optimal-order?materia=Dir").json()
        score_chave = next(o for o in data["ordem"] if o["id"] == chave)["score"]
        score_solto = next(o for o in data["ordem"] if o["id"] == solto)["score"]
        assert score_chave > score_solto, "tópico que desbloqueia outros tem prioridade"
        # e o campo desbloqueios reflete
        assert next(o for o in data["ordem"] if o["id"] == chave)["desbloqueios"] == 2

    def test_scoring_status_nao_iniciado_maior_que_concluido(self, client):
        """Regressão do bug: status canônico Title Case deve pontuar (Não
        Iniciado=+30 > Concluído=+0)."""
        _reset()
        novo = _add_topico("Dir", "Novo", status="Não Iniciado")
        feito = _add_topico("Dir", "Feito", status="Concluído")
        data = client.get("/api/knowledge-graph/optimal-order?materia=Dir").json()
        s_novo = next(o for o in data["ordem"] if o["id"] == novo)["score"]
        s_feito = next(o for o in data["ordem"] if o["id"] == feito)["score"]
        assert s_novo > s_feito, "Não Iniciado deve pontuar mais que Concluído (bug de status corrigido)"
        # Diferença de status é 30 (novo também tem +10 de horas=0; feito idem),
        # então o delta relevante é o de status.
        assert s_novo - s_feito >= 30

    def test_edital_vazio(self, client):
        _reset()
        data = client.get("/api/knowledge-graph/optimal-order").json()
        assert data["ordem"] == []


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

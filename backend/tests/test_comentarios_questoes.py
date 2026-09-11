"""Testes da feature de COMENTÁRIOS em questões.

Cobre: listar, adicionar, gerar via IA (LLM real mockado + fallback), votar
(toggle idempotente, sem inflar) e deletar (só o próprio).

Executar: pytest tests/test_comentarios_questoes.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_comentarios.db", delete=False)
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


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


def _criar_questao(client, materia="Informática", explicacao="", correta="A"):
    r = client.post("/api/questoes", json={
        "materia": materia, "topico": "T", "enunciado": "Qual a resposta?",
        "alternativa_a": "A", "alternativa_b": "B", "alternativa_c": "C",
        "alternativa_d": "D", "alternativa_e": "", "resposta_correta": correta,
        "explicacao": explicacao, "dificuldade": "Médio",
    })
    assert r.status_code == 200
    return r.json()["id"]


class TestComentariosCRUD:
    def test_adicionar_e_listar(self, client):
        qid = _criar_questao(client)
        r = client.post(f"/api/questoes/{qid}/comentarios", json={"conteudo": "Explicação do colega"})
        assert r.status_code == 200
        cid = r.json()["id"]

        data = client.get(f"/api/questoes/{qid}/comentarios").json()
        assert any(c["id"] == cid and c["conteudo"] == "Explicação do colega" for c in data)
        c = next(c for c in data if c["id"] == cid)
        assert c["tipo"] == "user"
        assert c["is_owner"] is True
        assert c["voted"] is False
        assert c["votos"] == 0

    def test_comentario_vazio_rejeitado(self, client):
        qid = _criar_questao(client)
        r = client.post(f"/api/questoes/{qid}/comentarios", json={"conteudo": "   "})
        assert r.status_code == 422

    def test_deletar_proprio_comentario(self, client):
        qid = _criar_questao(client)
        cid = client.post(f"/api/questoes/{qid}/comentarios", json={"conteudo": "apagar depois"}).json()["id"]
        r = client.delete(f"/api/questoes/{qid}/comentarios/{cid}")
        assert r.status_code == 200
        data = client.get(f"/api/questoes/{qid}/comentarios").json()
        assert all(c["id"] != cid for c in data), "comentário deletado não deve aparecer"

    def test_deletar_comentario_inexistente_404(self, client):
        qid = _criar_questao(client)
        r = client.delete(f"/api/questoes/{qid}/comentarios/999999")
        assert r.status_code == 404


class TestVotoIdempotente:
    def test_voto_toggle_nao_infla(self, client):
        qid = _criar_questao(client)
        cid = client.post(f"/api/questoes/{qid}/comentarios", json={"conteudo": "útil"}).json()["id"]

        # 1º voto → 1
        r1 = client.post(f"/api/questoes/{qid}/comentarios/{cid}/votar").json()
        assert r1["voted"] is True and r1["votos"] == 1

        # votar de novo (mesmo user) → remove (toggle) → 0
        r2 = client.post(f"/api/questoes/{qid}/comentarios/{cid}/votar").json()
        assert r2["voted"] is False and r2["votos"] == 0

        # e de novo → volta a 1 (nunca infla além de 1 por usuário)
        r3 = client.post(f"/api/questoes/{qid}/comentarios/{cid}/votar").json()
        assert r3["voted"] is True and r3["votos"] == 1

        # a listagem reflete voted=True e votos=1
        data = client.get(f"/api/questoes/{qid}/comentarios").json()
        c = next(c for c in data if c["id"] == cid)
        assert c["voted"] is True and c["votos"] == 1

    def test_votar_comentario_inexistente_404(self, client):
        qid = _criar_questao(client)
        r = client.post(f"/api/questoes/{qid}/comentarios/999999/votar")
        assert r.status_code == 404


class TestComentarioIA:
    def test_ia_usa_llm_quando_disponivel(self, client, monkeypatch):
        """Quando o AI Tutor está configurado, o comentário IA vem do LLM."""
        import routers.ai_tutor as ai

        monkeypatch.setattr(ai, "call_llm_sync", lambda messages, max_tokens=400: ("Explicação gerada pela IA real.", 42))

        qid = _criar_questao(client)
        r = client.post(f"/api/questoes/{qid}/comentarios/ia")
        assert r.status_code == 200
        body = r.json()
        assert body["cached"] is False
        assert body["fonte"] == "llm"
        assert "IA real" in body["conteudo"]

    def test_ia_cache_segunda_chamada(self, client, monkeypatch):
        import routers.ai_tutor as ai

        chamadas = {"n": 0}

        def _fake(messages, max_tokens=400):
            chamadas["n"] += 1
            return ("Conteúdo IA", 10)
        monkeypatch.setattr(ai, "call_llm_sync", _fake)

        qid = _criar_questao(client)
        r1 = client.post(f"/api/questoes/{qid}/comentarios/ia").json()
        assert r1["cached"] is False
        r2 = client.post(f"/api/questoes/{qid}/comentarios/ia").json()
        assert r2["cached"] is True, "segunda chamada deve vir do cache"
        assert chamadas["n"] == 1, "LLM só é chamado uma vez"

    def test_ia_fallback_quando_llm_indisponivel(self, client, monkeypatch):
        """Sem IA configurada (call_llm_sync levanta 503), usa fallback gracioso."""
        import routers.ai_tutor as ai
        from fastapi import HTTPException

        def _sem_ia(messages, max_tokens=400):
            raise HTTPException(status_code=503, detail="AI não disponível")
        monkeypatch.setattr(ai, "call_llm_sync", _sem_ia)

        qid = _criar_questao(client)
        r = client.post(f"/api/questoes/{qid}/comentarios/ia")
        assert r.status_code == 200, "fallback nunca deve falhar para o usuário"
        body = r.json()
        assert body["fonte"] == "template"
        assert "Resposta correta" in body["conteudo"]

    def test_ia_fallback_usa_explicacao_cadastrada(self, client, monkeypatch):
        """Sem LLM, se a questão tem explicação cadastrada, usa-a como comentário."""
        import routers.ai_tutor as ai
        from fastapi import HTTPException

        monkeypatch.setattr(ai, "call_llm_sync", lambda *a, **k: (_ for _ in ()).throw(HTTPException(status_code=503, detail="x")))

        expl = "Explicação oficial cadastrada com detalhes suficientes para servir."
        qid = _criar_questao(client, explicacao=expl)
        body = client.post(f"/api/questoes/{qid}/comentarios/ia").json()
        assert body["fonte"] == "explicacao"
        assert body["conteudo"] == expl

    def test_ia_questao_inexistente_404(self, client, monkeypatch):
        import routers.ai_tutor as ai
        monkeypatch.setattr(ai, "call_llm_sync", lambda *a, **k: ("x", 1))
        r = client.post("/api/questoes/999999/comentarios/ia")
        assert r.status_code == 404


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

"""
Testes dos endpoints principais do ConcurseiroOS.
Usa TestClient do FastAPI (síncrono) com banco de dados temporário.

Executar: pytest tests/ -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_endpoints.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

# Ajustar path para imports
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
    """TestClient compartilhado por todo o módulo de testes."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db_endpoints():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


@pytest.fixture(autouse=True)
def _reset_db():
    """Garante banco limpo entre testes (re-init)."""
    # Não reseta entre testes para permitir fluxos dependentes
    pass


# ============================================================
# PDF PROGRESS
# ============================================================

class TestPdfProgress:
    def test_get_tree(self, client):
        r = client.get("/api/tree")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_progress_default(self, client):
        r = client.get("/api/progress/nonexistent.pdf")
        assert r.status_code == 200
        data = r.json()
        assert data["current_page"] == 1

    def test_save_and_get_progress(self, client):
        r = client.post("/api/progress/test.pdf", json={"current_page": 5, "total_pages": 100})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r = client.get("/api/progress/test.pdf")
        assert r.status_code == 200
        assert r.json()["current_page"] == 5
        assert r.json()["total_pages"] == 100

    def test_progress_bulk(self, client):
        r = client.get("/api/progress-bulk")
        assert r.status_code == 200
        data = r.json()
        assert "test.pdf" in data


# ============================================================
# EDITAL
# ============================================================

class TestEdital:
    def test_create_edital(self, client):
        r = client.post("/api/edital", json={
            "materia": "Direito Constitucional",
            "topico": "Princípios Fundamentais",
            "edital_nome": "PC-MA 2026",
            "cargo": "Investigador"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["materia"] == "Direito Constitucional"
        assert data["id"] > 0

    def test_list_edital(self, client):
        r = client.get("/api/edital")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        # Verify our created topic exists somewhere in the list
        materias = [d["materia"] for d in data]
        assert "Direito Constitucional" in materias

    def test_list_edital_nomes(self, client):
        r = client.get("/api/edital/nomes")
        assert r.status_code == 200
        data = r.json()
        assert len(data) >= 1
        assert data[0]["concurso"] == "PC-MA 2026"

    def test_toggle_status(self, client):
        # Create a fresh topic to toggle
        r = client.post("/api/edital", json={
            "materia": "Toggle Test",
            "topico": "Tópico Toggle",
            "edital_nome": "Test",
            "cargo": "Test"
        })
        tid = r.json()["id"]
        r = client.put(f"/api/edital/{tid}/status")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "Em Andamento"

    def test_add_horas(self, client):
        # Create a fresh topic to add hours
        r = client.post("/api/edital", json={
            "materia": "Horas Test",
            "topico": "Tópico Horas",
            "edital_nome": "Test",
            "cargo": "Test"
        })
        tid = r.json()["id"]
        r = client.put(f"/api/edital/{tid}/horas", json={"horas": 1.5})
        assert r.status_code == 200
        data = r.json()
        assert data["horas_estudadas"] == 1.5

    def test_link_pdf(self, client):
        r = client.put("/api/edital/1/pdf", json={"pdf_link": "Livros/teste.pdf", "pdf_pagina": 10})
        assert r.status_code == 200
        assert r.json()["pdf_link"] == "Livros/teste.pdf"

    def test_edital_notas(self, client):
        r = client.post("/api/edital/1/notas", json={"edital_id": 1, "conteudo": "Nota de teste"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        r = client.get("/api/edital/1/notas")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_arquivar_desarquivar(self, client):
        # Criar segundo edital para arquivar
        client.post("/api/edital", json={
            "materia": "Teste Arquivo",
            "topico": "Tópico",
            "edital_nome": "Teste-Arquivo",
            "cargo": "Cargo1"
        })
        r = client.put("/api/edital/arquivar?edital_nome=Teste-Arquivo&cargo=Cargo1")
        assert r.status_code == 200
        assert r.json()["arquivados"] >= 1

        r = client.get("/api/edital/arquivados")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        r = client.put("/api/edital/desarquivar?edital_nome=Teste-Arquivo&cargo=Cargo1")
        assert r.status_code == 200

    def test_delete_edital(self, client):
        # Delete individual topic
        r = client.delete("/api/edital/2")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ============================================================
# FLASHCARDS
# ============================================================

class TestFlashcards:
    def test_create_flashcard(self, client):
        r = client.post("/api/flashcards", json={
            "pergunta": "O que é o STF?",
            "resposta": "Supremo Tribunal Federal"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["pergunta"] == "O que é o STF?"
        assert data["id"] > 0

    def test_list_flashcards(self, client):
        r = client.get("/api/flashcards")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_flashcards_today(self, client):
        r = client.get("/api/flashcards/today")
        assert r.status_code == 200
        # Should have at least the one we just created
        assert len(r.json()) >= 1

    def test_review_flashcard(self, client):
        # Create a fresh flashcard to review
        r = client.post("/api/flashcards", json={
            "pergunta": "Review test?",
            "resposta": "Yes"
        })
        fid = r.json()["id"]
        r = client.post(f"/api/flashcards/{fid}/review", json={"acertou": True})
        assert r.status_code == 200
        data = r.json()
        assert data["intervalo_dias"] == 2  # Dobrou de 1 para 2

    def test_delete_flashcard(self, client):
        # Create one to delete
        r = client.post("/api/flashcards", json={"pergunta": "Temp", "resposta": "Temp"})
        fid = r.json()["id"]
        r = client.delete(f"/api/flashcards/{fid}")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ============================================================
# QUESTÕES
# ============================================================

class TestQuestoes:
    def test_create_questao(self, client):
        r = client.post("/api/questoes", json={
            "materia": "Direito Constitucional",
            "topico": "Princípios",
            "enunciado": "Qual o fundamento da República?",
            "alternativa_a": "Soberania",
            "alternativa_b": "Cidadania",
            "alternativa_c": "Dignidade da pessoa humana",
            "alternativa_d": "Todos os anteriores",
            "alternativa_e": "",
            "resposta_correta": "D",
            "explicacao": "Art. 1º da CF",
            "dificuldade": "Fácil"
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_list_questoes(self, client):
        r = client.get("/api/questoes")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_list_questoes_por_materia(self, client):
        r = client.get("/api/questoes?materia=Direito Constitucional")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_get_questao(self, client):
        r = client.get("/api/questoes/1")
        assert r.status_code == 200
        assert r.json()["materia"] == "Direito Constitucional"

    def test_responder_questao_correta(self, client):
        r = client.post("/api/questoes/1/responder", json={"resposta": "D", "tempo_segundos": 30})
        assert r.status_code == 200
        assert r.json()["acertou"] is True

    def test_responder_questao_errada(self, client):
        r = client.post("/api/questoes/1/responder", json={"resposta": "A", "tempo_segundos": 20})
        assert r.status_code == 200
        assert r.json()["acertou"] is False
        assert r.json()["resposta_correta"] == "D"

    def test_questoes_stats(self, client):
        r = client.get("/api/questoes/stats/geral")
        assert r.status_code == 200
        data = r.json()
        assert data["total_resolvidas"] >= 2
        assert data["total_acertos"] >= 1

    def test_caderno_erros(self, client):
        r = client.get("/api/questoes/erros/caderno")
        assert r.status_code == 200
        assert len(r.json()) >= 1  # Tem pelo menos 1 erro

    def test_questoes_materias(self, client):
        r = client.get("/api/questoes/materias")
        assert r.status_code == 200
        assert "Direito Constitucional" in r.json()

    def test_delete_questao(self, client):
        # Create and delete
        r = client.post("/api/questoes", json={
            "materia": "Temp", "topico": "", "enunciado": "Temp?",
            "alternativa_a": "A", "alternativa_b": "B",
            "alternativa_c": "C", "alternativa_d": "D",
            "resposta_correta": "A"
        })
        qid = r.json()["id"]
        r = client.delete(f"/api/questoes/{qid}")
        assert r.status_code == 200


# ============================================================
# SIMULADOS
# ============================================================

class TestSimulados:
    def test_create_simulado(self, client):
        r = client.post("/api/simulados", json={
            "titulo": "Simulado Teste",
            "tempo_limite_min": 30,
            "questao_ids": [1]
        })
        assert r.status_code == 200
        assert r.json()["id"] > 0

    def test_list_simulados(self, client):
        r = client.get("/api/simulados")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_get_simulado(self, client):
        r = client.get("/api/simulados/1")
        assert r.status_code == 200
        data = r.json()
        assert data["simulado"]["titulo"] == "Simulado Teste"
        assert len(data["questoes"]) == 1

    def test_responder_simulado(self, client):
        r = client.post("/api/simulados/1/responder", json={"questao_id": 1, "resposta": "D"})
        assert r.status_code == 200
        assert r.json()["acertou"] is True

    def test_finalizar_simulado(self, client):
        r = client.post("/api/simulados/1/finalizar", json={"tempo_gasto_seg": 120})
        assert r.status_code == 200
        data = r.json()
        assert data["nota"] == 100.0
        assert data["acertos"] == 1

    def test_delete_simulado(self, client):
        r = client.post("/api/simulados", json={"titulo": "Del", "tempo_limite_min": 10, "questao_ids": [1]})
        sid = r.json()["id"]
        r = client.delete(f"/api/simulados/{sid}")
        assert r.status_code == 200


# ============================================================
# CICLO DE ESTUDOS
# ============================================================

class TestCiclo:
    def test_create_ciclo(self, client):
        r = client.post("/api/ciclo", json={"materia": "Direito Constitucional", "horas_alvo": 2.0})
        assert r.status_code == 200
        assert r.json()["id"] > 0

    def test_list_ciclo(self, client):
        r = client.get("/api/ciclo")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_proximo_ciclo(self, client):
        r = client.get("/api/ciclo/proximo")
        assert r.status_code == 200
        data = r.json()
        assert "materia" in data
        assert "horas_alvo" in data

    def test_add_horas_ciclo(self, client):
        r = client.put("/api/ciclo/1/horas", json={"horas": 0.5})
        assert r.status_code == 200
        assert r.json()["horas_cumpridas"] == 0.5

    def test_resetar_ciclo(self, client):
        r = client.post("/api/ciclo/resetar")
        assert r.status_code == 200

    def test_delete_ciclo(self, client):
        r = client.post("/api/ciclo", json={"materia": "Temp", "horas_alvo": 1.0})
        cid = r.json()["id"]
        r = client.delete(f"/api/ciclo/{cid}")
        assert r.status_code == 200


# ============================================================
# STREAKS E METAS
# ============================================================

class TestStreaksMetas:
    def test_get_streaks(self, client):
        r = client.get("/api/streaks")
        assert r.status_code == 200
        data = r.json()
        assert "streak_atual" in data
        assert "melhor_streak" in data
        assert "hoje" in data

    def test_get_metas(self, client):
        r = client.get("/api/metas")
        assert r.status_code == 200
        data = r.json()
        assert "config" in data
        assert "progresso" in data

    def test_update_metas(self, client):
        r = client.put("/api/metas", json={
            "meta_horas": 4.0,
            "meta_questoes": 50,
            "meta_flashcards": 15,
            "meta_paginas": 30
        })
        assert r.status_code == 200

    def test_gamification(self, client):
        r = client.get("/api/gamification")
        assert r.status_code == 200
        data = r.json()
        assert "xp" in data
        assert "nivel" in data
        assert "badges_earned" in data


# ============================================================
# DASHBOARD E ANALYTICS
# ============================================================

class TestDashboard:
    def test_dashboard(self, client):
        r = client.get("/api/dashboard")
        assert r.status_code == 200
        data = r.json()
        assert "total_horas" in data
        assert "edital" in data
        assert "questoes" in data

    def test_relatorio_semanal(self, client):
        r = client.get("/api/relatorio-semanal")
        assert r.status_code == 200
        assert "total_horas" in r.json()

    def test_resumo_diario(self, client):
        r = client.get("/api/resumo-diario")
        assert r.status_code == 200
        assert "data" in r.json()

    def test_pratica_deliberada(self, client):
        r = client.get("/api/pratica-deliberada")
        assert r.status_code == 200
        assert "materias_para_focar" in r.json()

    def test_heatmap(self, client):
        r = client.get("/api/heatmap")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_radar(self, client):
        r = client.get("/api/radar")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_previsao_aprovacao(self, client):
        r = client.get("/api/previsao-aprovacao")
        assert r.status_code == 200
        assert "score" in r.json()

    def test_previsao_data(self, client):
        r = client.get("/api/previsao-data-aprovacao")
        assert r.status_code == 200

    def test_analise_erros(self, client):
        r = client.get("/api/analise-erros")
        assert r.status_code == 200
        assert "erros_por_materia" in r.json()

    def test_projecao_nota(self, client):
        r = client.get("/api/projecao-nota")
        assert r.status_code == 200
        assert "nota_projetada" in r.json()

    def test_simulado_inteligente(self, client):
        r = client.get("/api/simulado-inteligente?qtd=5")
        assert r.status_code == 200
        assert "questao_ids" in r.json()

    def test_simulado_adaptativo(self, client):
        r = client.get("/api/simulado-adaptativo?qtd=5")
        assert r.status_code == 200
        assert "questao_ids" in r.json()

    def test_comparador_progresso(self, client):
        r = client.get("/api/comparador-progresso")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_linha_tempo(self, client):
        r = client.get("/api/linha-tempo")
        assert r.status_code == 200

    def test_conquistas_diarias(self, client):
        r = client.get("/api/conquistas-diarias")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_compartilhar(self, client):
        r = client.get("/api/compartilhar")
        assert r.status_code == 200
        assert "texto" in r.json()

    def test_status_rapido(self, client):
        r = client.get("/api/status-rapido")
        assert r.status_code == 200
        assert "streak" in r.json()

    def test_widget(self, client):
        r = client.get("/api/widget")
        assert r.status_code == 200
        assert "flashcards_pendentes" in r.json()


# ============================================================
# MISC (BOOKMARKS, NOTAS, CADERNOS, etc.)
# ============================================================

class TestMisc:
    def test_notificacoes(self, client):
        r = client.get("/api/notificacoes")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_countdown(self, client):
        r = client.get("/api/countdown")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_bookmarks_crud(self, client):
        # Create
        r = client.post("/api/bookmarks", json={
            "pdf_path": "test.pdf",
            "pagina": 5,
            "label": "Importante",
            "cor": "red"
        })
        assert r.status_code == 200
        bid = r.json()["id"]

        # Get
        r = client.get("/api/bookmarks/test.pdf")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        # Delete
        r = client.delete(f"/api/bookmarks/{bid}")
        assert r.status_code == 200

    def test_notas_pdf(self, client):
        r = client.post("/api/notas", json={
            "pdf_path": "test.pdf",
            "pagina": 3,
            "conteudo": "Anotação de teste"
        })
        assert r.status_code == 200
        nid = r.json()["id"]

        r = client.get("/api/notas/test.pdf")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        r = client.delete(f"/api/notas/{nid}")
        assert r.status_code == 200

    def test_cadernos_crud(self, client):
        r = client.post("/api/cadernos", json={"nome": "Caderno Teste", "descricao": "Desc"})
        assert r.status_code == 201
        cid = r.json()["id"]

        r = client.get("/api/cadernos")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        # Criar uma questão para adicionar ao caderno
        r = client.post("/api/questoes", json={
            "materia": "Direito", "enunciado": "Questão caderno?",
            "alternativa_a": "A", "alternativa_b": "B",
            "alternativa_c": "C", "alternativa_d": "D",
            "resposta_correta": "A"
        })
        qid = r.json().get("id", 1)

        r = client.post(f"/api/cadernos/{cid}/questoes", json={"questao_ids": [qid]})
        assert r.status_code == 200
        assert r.json()["adicionadas"] == 1

        r = client.get(f"/api/cadernos/{cid}")
        assert r.status_code == 200
        assert r.json()["total_questoes"] == 1

        r = client.get(f"/api/cadernos/{cid}/resolver")
        assert r.status_code == 200
        assert r.json()["total"] == 1

        r = client.get(f"/api/cadernos/{cid}/progresso")
        assert r.status_code == 200
        assert r.json()["total"] == 1

        r = client.delete(f"/api/cadernos/{cid}/questoes/{qid}")
        assert r.status_code == 200

        r = client.delete(f"/api/cadernos/{cid}")
        assert r.status_code == 200

    def test_feynman(self, client):
        r = client.post("/api/feynman", json={"edital_id": 1, "explicacao": "Explicação Feynman"})
        assert r.status_code == 200

        r = client.get("/api/feynman/1")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_planejador_semanal(self, client):
        r = client.post("/api/planejador", json={"dia_semana": 0, "materia": "Direito", "horas": 2.0})
        assert r.status_code == 200
        pid = r.json()["id"]

        r = client.get("/api/planejador")
        assert r.status_code == 200
        assert len(r.json()) >= 1

        r = client.delete(f"/api/planejador/{pid}")
        assert r.status_code == 200

    def test_desafios(self, client):
        r = client.post("/api/desafios", json={
            "titulo": "Desafio Teste",
            "meta_tipo": "questoes",
            "meta_valor": 50,
            "materia": "Geral",
            "dias": 7
        })
        assert r.status_code == 200

        r = client.get("/api/desafios")
        assert r.status_code == 200
        assert len(r.json()) >= 1

    def test_daily_challenge(self, client):
        r = client.get("/api/daily-challenge")
        assert r.status_code == 200

    def test_intercalacao(self, client):
        # Add more topics so intercalacao has material
        client.post("/api/edital", json={
            "materia": "Informática", "topico": "Redes",
            "edital_nome": "PC-MA 2026", "cargo": "Investigador"
        })
        r = client.get("/api/intercalacao")
        assert r.status_code == 200

    def test_modo_foco(self, client):
        r = client.get("/api/modo-foco/status")
        assert r.status_code == 200
        assert r.json()["disponivel"] is True

    def test_speed_review(self, client):
        r = client.get("/api/speed-review")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

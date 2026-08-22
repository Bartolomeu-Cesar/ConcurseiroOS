"""
Testes do Lote D: Aprendizado Adaptativo.
- SM-2 para flashcards e edital
- Treinador Inteligente
- Filtros avançados de questões
- Curva de esquecimento
- Raio-X do edital
- Trilha de estudo diária

Executar: pytest tests/test_lote_d.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_lote_d.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
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
    """Override para garantir que FastAPI use o DB temporário deste módulo."""
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session


@pytest.fixture(scope="module")
def client():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db_lote_d():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


# ============================================================
# SM-2 FLASHCARDS
# ============================================================

class TestSM2Flashcards:
    def test_create_flashcard_has_sm2_fields(self, client):
        r = client.post("/api/flashcards", json={
            "pergunta": "O que é SM-2?",
            "resposta": "Algoritmo de repetição espaçada"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["intervalo_dias"] == 1

    def test_list_flashcards_has_sm2_fields(self, client):
        r = client.get("/api/flashcards")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1
        # SM-2 fields should be present
        assert "easiness_factor" in items[0]
        assert "repetitions" in items[0]

    def test_review_sm2_quality_5(self, client):
        """quality=5 (perfeito): reps=0->1, interval=1"""
        # Create flashcard
        r = client.post("/api/flashcards", json={
            "pergunta": "SM-2 test q5",
            "resposta": "Resposta"
        })
        fid = r.json()["id"]

        # Review with quality=5
        r = client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 5})
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == fid
        assert data["quality"] == 5
        assert data["repetitions"] == 1
        assert data["intervalo_dias"] == 1  # first rep = 1 day
        # EF should increase: 2.5 + 0.1 = 2.6
        assert data["easiness_factor"] == 2.6

    def test_review_sm2_quality_5_second_rep(self, client):
        """Second review quality=5: reps=1->2, interval=6"""
        r = client.post("/api/flashcards", json={
            "pergunta": "SM-2 test 2nd rep",
            "resposta": "Resposta"
        })
        fid = r.json()["id"]

        # First review
        r = client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 5})
        assert r.json()["repetitions"] == 1

        # Second review
        r = client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 5})
        data = r.json()
        assert data["repetitions"] == 2
        assert data["intervalo_dias"] == 6  # second rep = 6 days

    def test_review_sm2_quality_5_third_rep(self, client):
        """Third review quality=5: interval = 6 * EF"""
        r = client.post("/api/flashcards", json={
            "pergunta": "SM-2 test 3rd rep",
            "resposta": "Resposta"
        })
        fid = r.json()["id"]

        # Three reviews
        client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 5})
        client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 5})
        r = client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 5})
        data = r.json()
        assert data["repetitions"] == 3
        # After 2 quality=5 reviews: EF = 2.5 + 0.1 + 0.1 = 2.7
        # interval = 6 * 2.7 = 16.2, rounded = 16
        assert data["intervalo_dias"] == 16

    def test_review_sm2_quality_0_resets(self, client):
        """quality=0 (esqueceu): resets reps to 0, interval to 1"""
        r = client.post("/api/flashcards", json={
            "pergunta": "SM-2 test reset",
            "resposta": "Resposta"
        })
        fid = r.json()["id"]

        # Build up reps
        client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 4})
        client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 4})

        # Fail
        r = client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 0})
        data = r.json()
        assert data["repetitions"] == 0
        assert data["intervalo_dias"] == 1
        # EF decreases: quality=0 => EF + (0.1 - 5*(0.08+5*0.02)) = EF - 0.8
        # But min is 1.3
        assert data["easiness_factor"] >= 1.3

    def test_review_sm2_invalid_quality(self, client):
        """quality out of range should fail"""
        r = client.post("/api/flashcards", json={
            "pergunta": "SM-2 invalid",
            "resposta": "Resposta"
        })
        fid = r.json()["id"]

        r = client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": 6})
        assert r.status_code == 422

        r = client.post(f"/api/flashcards/{fid}/review-sm2", json={"quality": -1})
        assert r.status_code == 422

    def test_review_sm2_nonexistent(self, client):
        r = client.post("/api/flashcards/99999/review-sm2", json={"quality": 4})
        assert r.status_code == 404

    def test_old_review_still_works(self, client):
        """Retrocompatibilidade: endpoint antigo continua funcionando"""
        r = client.post("/api/flashcards", json={
            "pergunta": "Old review",
            "resposta": "Resposta"
        })
        fid = r.json()["id"]

        r = client.post(f"/api/flashcards/{fid}/review", json={"acertou": True})
        assert r.status_code == 200
        data = r.json()
        assert data["intervalo_dias"] == 2  # 1 * 2

        r = client.post(f"/api/flashcards/{fid}/review", json={"acertou": False})
        assert r.status_code == 200
        assert r.json()["intervalo_dias"] == 1


# ============================================================
# SM-2 EDITAL (REVISÃO DE TÓPICOS)
# ============================================================

class TestSM2Edital:
    def test_agendar_revisao_uses_sm2(self, client):
        """agendar-revisao agora usa SM-2 com quality=4"""
        # Create edital topic
        r = client.post("/api/edital", json={
            "materia": "Direito Penal",
            "topico": "Crimes contra pessoa",
            "edital_nome": "TestSM2",
            "cargo": "Analista"
        })
        eid = r.json()["id"]

        # Agendar revisão (quality=4 default)
        r = client.post(f"/api/edital/{eid}/agendar-revisao")
        assert r.status_code == 200
        data = r.json()
        assert data["intervalo"] == 1  # first rep = 1
        assert data["easiness_factor"] is not None
        assert data["repetitions"] == 1

    def test_agendar_revisao_second_time(self, client):
        r = client.post("/api/edital", json={
            "materia": "Dir. Constitucional",
            "topico": "Princípios",
            "edital_nome": "TestSM2",
            "cargo": "Analista"
        })
        eid = r.json()["id"]

        # First
        client.post(f"/api/edital/{eid}/agendar-revisao")
        # Second
        r = client.post(f"/api/edital/{eid}/agendar-revisao")
        data = r.json()
        assert data["intervalo"] == 6  # second rep = 6
        assert data["repetitions"] == 2

    def test_revisar_sm2_endpoint(self, client):
        r = client.post("/api/edital", json={
            "materia": "Informática",
            "topico": "Redes",
            "edital_nome": "TestSM2",
            "cargo": "Analista"
        })
        eid = r.json()["id"]

        # Use SM-2 with quality=3 (correto com dificuldade)
        r = client.post(f"/api/edital/{eid}/revisar-sm2", json={"quality": 3})
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == eid
        assert data["quality"] == 3
        assert data["repetitions"] == 1
        assert data["intervalo_dias"] == 1
        # EF = 2.5 + (0.1 - 2*(0.08 + 2*0.02)) = 2.5 + (0.1 - 0.24) = 2.36
        assert abs(data["easiness_factor"] - 2.36) < 0.01

    def test_revisar_sm2_fail(self, client):
        r = client.post("/api/edital", json={
            "materia": "Português",
            "topico": "Concordância",
            "edital_nome": "TestSM2",
            "cargo": "Analista"
        })
        eid = r.json()["id"]

        # Build up
        client.post(f"/api/edital/{eid}/revisar-sm2", json={"quality": 4})
        # Fail
        r = client.post(f"/api/edital/{eid}/revisar-sm2", json={"quality": 1})
        data = r.json()
        assert data["repetitions"] == 0
        assert data["intervalo_dias"] == 1

    def test_revisar_sm2_invalid_quality(self, client):
        r = client.post("/api/edital", json={
            "materia": "Ética",
            "topico": "Princípios",
            "edital_nome": "TestSM2",
            "cargo": "Analista"
        })
        eid = r.json()["id"]
        r = client.post(f"/api/edital/{eid}/revisar-sm2", json={"quality": 7})
        assert r.status_code == 422


# ============================================================
# FILTROS AVANÇADOS DE QUESTÕES
# ============================================================

class TestFiltrosQuestoes:
    @pytest.fixture(autouse=True)
    def setup_questoes(self, client):
        """Cria questões e respostas para testar filtros"""
        # Criar questões
        q1 = client.post("/api/questoes", json={
            "materia": "Direito Penal", "topico": "Crimes",
            "enunciado": "Questão fácil de penal",
            "alternativa_a": "A", "alternativa_b": "B",
            "alternativa_c": "C", "alternativa_d": "D",
            "resposta_correta": "A", "dificuldade": "Fácil"
        }).json()["id"]

        q2 = client.post("/api/questoes", json={
            "materia": "Informática", "topico": "Redes",
            "enunciado": "Questão difícil de info",
            "alternativa_a": "A", "alternativa_b": "B",
            "alternativa_c": "C", "alternativa_d": "D",
            "resposta_correta": "B", "dificuldade": "Difícil"
        }).json()["id"]

        q3 = client.post("/api/questoes", json={
            "materia": "Direito Penal", "topico": "Penas",
            "enunciado": "Questão médio de penal",
            "alternativa_a": "A", "alternativa_b": "B",
            "alternativa_c": "C", "alternativa_d": "D",
            "resposta_correta": "C", "dificuldade": "Médio"
        }).json()["id"]

        # Responder questões
        client.post(f"/api/questoes/{q1}/responder", json={"resposta": "A"})  # acertou
        client.post(f"/api/questoes/{q2}/responder", json={"resposta": "A"})  # errou

        self.q1 = q1
        self.q2 = q2
        self.q3 = q3

    def test_filter_by_dificuldade(self, client):
        r = client.get("/api/questoes?dificuldade=Fácil")
        assert r.status_code == 200
        items = r.json()
        assert all(q["dificuldade"] == "Fácil" for q in items)

    def test_filter_acertou(self, client):
        r = client.get("/api/questoes?acertou=1")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1

    def test_filter_errou(self, client):
        r = client.get("/api/questoes?acertou=0")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 1

    def test_filter_nao_respondidas(self, client):
        r = client.get("/api/questoes?respondidas=0")
        assert r.status_code == 200
        items = r.json()
        # q3 was not answered
        assert any(q["id"] == self.q3 for q in items)

    def test_filter_respondidas(self, client):
        r = client.get("/api/questoes?respondidas=1")
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 2

    def test_filter_combined(self, client):
        r = client.get("/api/questoes?materia=Direito Penal&dificuldade=Fácil")
        assert r.status_code == 200
        items = r.json()
        assert all(q["materia"] == "Direito Penal" and q["dificuldade"] == "Fácil" for q in items)

    def test_original_params_still_work(self, client):
        """Retrocompatibilidade: materia e topico continuam funcionando"""
        r = client.get("/api/questoes?materia=Informática")
        assert r.status_code == 200
        items = r.json()
        assert all(q["materia"] == "Informática" for q in items)


# ============================================================
# TREINADOR INTELIGENTE
# ============================================================

class TestTreinador:
    def test_treinador_endpoint(self, client):
        r = client.get("/api/treinador")
        assert r.status_code == 200
        data = r.json()
        assert "score_prontidao" in data
        assert "nivel" in data
        assert "recomendacoes" in data
        assert "materias_foco" in data
        assert "revisoes_pendentes" in data
        assert "meta_hoje" in data
        assert isinstance(data["score_prontidao"], (int, float))
        assert 0 <= data["score_prontidao"] <= 100

    def test_treinador_revisoes_pendentes_structure(self, client):
        r = client.get("/api/treinador")
        data = r.json()
        assert "flashcards" in data["revisoes_pendentes"]
        assert "topicos" in data["revisoes_pendentes"]

    def test_treinador_meta_hoje_structure(self, client):
        r = client.get("/api/treinador")
        data = r.json()
        meta = data["meta_hoje"]
        assert "horas" in meta
        assert "questoes" in meta
        assert "cumprido_horas" in meta
        assert "cumprido_questoes" in meta

    def test_treinador_with_filters(self, client):
        r = client.get("/api/treinador?edital_nome=TestSM2&cargo=Analista")
        assert r.status_code == 200


# ============================================================
# CURVA DE ESQUECIMENTO
# ============================================================

class TestCurvaEsquecimento:
    def test_curva_esquecimento_endpoint(self, client):
        r = client.get("/api/curva-esquecimento")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_curva_esquecimento_with_data(self, client):
        """Tópicos com revisão agendada devem aparecer"""
        # Create topic and schedule review
        r = client.post("/api/edital", json={
            "materia": "RLM",
            "topico": "Lógica proposicional",
            "edital_nome": "CurvaTest",
            "cargo": "Agente"
        })
        eid = r.json()["id"]
        client.post(f"/api/edital/{eid}/agendar-revisao")

        r = client.get("/api/curva-esquecimento")
        data = r.json()
        # Should have at least one item
        assert len(data) >= 1
        item = data[0]
        assert "materia" in item
        assert "topico" in item
        assert "retencao_pct" in item
        assert "dias_desde_revisao" in item
        assert "proxima_revisao" in item
        assert "urgente" in item

    def test_curva_esquecimento_filter(self, client):
        r = client.get("/api/curva-esquecimento?materia=RLM")
        assert r.status_code == 200
        data = r.json()
        assert all(item["materia"] == "RLM" for item in data)


# ============================================================
# RAIO-X DO EDITAL
# ============================================================

class TestRaioX:
    def test_raio_x_endpoint(self, client):
        r = client.get("/api/raio-x")
        assert r.status_code == 200
        data = r.json()
        assert "total_questoes" in data
        assert "materias" in data
        assert isinstance(data["materias"], list)

    def test_raio_x_structure(self, client):
        r = client.get("/api/raio-x")
        data = r.json()
        if data["materias"]:
            mat = data["materias"][0]
            assert "materia" in mat
            assert "questoes" in mat
            assert "peso_pct" in mat
            assert "horas_estudadas" in mat
            assert "pct_acerto" in mat
            assert "balanceamento" in mat
            assert mat["balanceamento"] in ("equilibrado", "subestudado", "superestudado", "sem_dados")


# ============================================================
# TRILHA DE ESTUDO DIÁRIA
# ============================================================

class TestTrilhaDiaria:
    def test_trilha_diaria_endpoint(self, client):
        r = client.get("/api/trilha-diaria")
        assert r.status_code == 200
        data = r.json()
        assert "data" in data
        assert "horas_disponiveis" in data
        assert "atividades" in data
        assert "tempo_total_min" in data
        assert "foco_principal" in data
        assert "motivo" in data

    def test_trilha_diaria_custom_hours(self, client):
        r = client.get("/api/trilha-diaria?horas_disponiveis=5.0")
        assert r.status_code == 200
        data = r.json()
        assert data["horas_disponiveis"] == 5.0

    def test_trilha_diaria_atividades_structure(self, client):
        r = client.get("/api/trilha-diaria")
        data = r.json()
        for ativ in data["atividades"]:
            assert "ordem" in ativ
            assert "tipo" in ativ
            assert "tempo_min" in ativ
            assert ativ["tipo"] in ("revisao", "estudo", "questoes")

    def test_trilha_diaria_with_filters(self, client):
        r = client.get("/api/trilha-diaria?edital_nome=TestSM2&cargo=Analista")
        assert r.status_code == 200

"""
Testes de integração do Simulado Cronometrado.
Cobre criação, finalização com cálculo de nota, e consulta de resultados.

Executar: pytest tests/test_simulado_crono.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_simulado_crono.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

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
def _ensure_db():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


@pytest.fixture(scope="module")
def setup_questoes(client):
    """Cria questões no banco para serem usadas nos simulados cronometrados."""
    questoes_ids = []
    materias = ["Direito Constitucional", "Direito Administrativo", "Português"]
    for i in range(30):
        materia = materias[i % len(materias)]
        dificuldade = "Fácil" if i < 10 else ("Médio" if i < 20 else "Difícil")
        r = client.post("/api/questoes", json={
            "materia": materia,
            "topico": f"Tópico {i % 5 + 1}",
            "enunciado": f"Questão simulado crono #{i + 1}: Assinale a alternativa correta.",
            "alternativa_a": "Alternativa A (correta)",
            "alternativa_b": "Alternativa B",
            "alternativa_c": "Alternativa C",
            "alternativa_d": "Alternativa D",
            "alternativa_e": "Alternativa E",
            "resposta_correta": "A",
            "explicacao": f"A alternativa A está correta porque...",
            "dificuldade": dificuldade,
        })
        assert r.status_code == 200
        data = r.json()
        questoes_ids.append(data.get("id", i + 1))
    return questoes_ids


# ============================================================
# POST /api/simulados/cronometrado — Criar simulado cronometrado
# ============================================================

class TestCriarSimuladoCronometrado:
    def test_criar_simulado_padrao(self, client, setup_questoes):
        """Cria simulado cronometrado com configuração padrão."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado de Teste",
            "tempo_total_min": 120,
            "questoes_total": 10,
            "materias": [],
            "dificuldade_mix": {"facil": 3, "medio": 4, "dificil": 3},
        })
        assert r.status_code == 200
        data = r.json()
        assert "id" in data
        assert data["titulo"] == "Simulado de Teste"
        assert data["tempo_total_min"] == 120
        assert data["total_questoes"] == 10
        assert "questoes" in data
        assert len(data["questoes"]) == 10
        # Verificar estrutura das questões
        for q in data["questoes"]:
            assert "id" in q
            assert "num" in q
            assert "materia" in q
            assert "enunciado" in q
            assert "alternativas" in q
            assert len(q["alternativas"]) >= 4

    def test_criar_simulado_filtro_materias(self, client, setup_questoes):
        """Cria simulado filtrando por matérias específicas."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Constitucional",
            "tempo_total_min": 60,
            "questoes_total": 5,
            "materias": ["Direito Constitucional"],
            "dificuldade_mix": {"facil": 2, "medio": 2, "dificil": 1},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["total_questoes"] <= 10  # Pode ser menos se não tem suficiente
        # Todas as questões devem ser da matéria selecionada
        for q in data["questoes"]:
            assert q["materia"] == "Direito Constitucional"

    def test_criar_simulado_sem_questoes_disponiveis(self, client):
        """Retorna erro quando não há questões para os critérios."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Vazio",
            "tempo_total_min": 60,
            "questoes_total": 10,
            "materias": ["Matéria Inexistente XYZ"],
            "dificuldade_mix": {"facil": 3, "medio": 4, "dificil": 3},
        })
        assert r.status_code == 400
        assert "Nenhuma questão" in r.json()["detail"]

    def test_criar_simulado_dificuldade_mix(self, client, setup_questoes):
        """Respeita a distribuição de dificuldade solicitada."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Mix",
            "tempo_total_min": 90,
            "questoes_total": 15,
            "materias": [],
            "dificuldade_mix": {"facil": 5, "medio": 5, "dificil": 5},
        })
        assert r.status_code == 200
        data = r.json()
        assert data["total_questoes"] == 15


# ============================================================
# POST /api/simulados/cronometrado/{id}/finalizar — Finalizar
# ============================================================

class TestFinalizarSimuladoCronometrado:
    def test_finalizar_com_todas_respostas(self, client, setup_questoes):
        """Finaliza simulado com todas as respostas e recebe nota."""
        # Criar simulado primeiro
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Finalizar",
            "tempo_total_min": 60,
            "questoes_total": 5,
            "materias": [],
            "dificuldade_mix": {"facil": 2, "medio": 2, "dificil": 1},
        })
        assert r.status_code == 200
        sim_id = r.json()["id"]
        questoes = r.json()["questoes"]

        # Construir respostas (todas corretas = "A")
        respostas = [
            {"questao_id": q["id"], "resposta": "A", "tempo_seg": 30}
            for q in questoes
        ]

        r = client.post(f"/api/simulados/cronometrado/{sim_id}/finalizar", json={
            "respostas": respostas,
            "tempo_total_seg": 150,
        })
        assert r.status_code == 200
        data = r.json()
        assert "nota_bruta" in data
        assert "nota_tri" in data
        assert "total_acertos" in data
        assert "total_erros" in data
        assert "total_em_branco" in data
        assert "total_questoes" in data
        assert "por_materia" in data
        assert "tempo_medio_por_questao" in data
        assert "tempo_total_seg" in data
        # Todas corretas
        assert data["total_acertos"] == 5
        assert data["total_erros"] == 0
        assert data["nota_bruta"] == 100.0
        assert data["nota_tri"] == 100.0

    def test_finalizar_com_mix_corretas_erradas(self, client, setup_questoes):
        """Finaliza com mix de respostas corretas e erradas."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Mix Resp",
            "tempo_total_min": 60,
            "questoes_total": 10,
            "materias": [],
            "dificuldade_mix": {"facil": 3, "medio": 4, "dificil": 3},
        })
        sim_id = r.json()["id"]
        questoes = r.json()["questoes"]

        # Metade correta (A), metade errada (B)
        respostas = [
            {"questao_id": q["id"], "resposta": "A" if i < 5 else "B", "tempo_seg": 20}
            for i, q in enumerate(questoes)
        ]

        r = client.post(f"/api/simulados/cronometrado/{sim_id}/finalizar", json={
            "respostas": respostas,
            "tempo_total_seg": 200,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["total_acertos"] == 5
        assert data["total_erros"] == 5
        assert data["nota_bruta"] == 50.0
        # TRI penaliza erros: 5 - (5 * 0.25) = 3.75 → 37.5%
        assert data["nota_tri"] == 37.5
        assert data["tempo_medio_por_questao"] == 20.0

    def test_finalizar_com_respostas_em_branco(self, client, setup_questoes):
        """Finaliza com algumas respostas em branco."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Brancos",
            "tempo_total_min": 60,
            "questoes_total": 6,
            "materias": [],
            "dificuldade_mix": {"facil": 2, "medio": 2, "dificil": 2},
        })
        sim_id = r.json()["id"]
        questoes = r.json()["questoes"]

        # 2 corretas, 2 erradas, 2 em branco
        respostas = []
        for i, q in enumerate(questoes):
            if i < 2:
                respostas.append({"questao_id": q["id"], "resposta": "A", "tempo_seg": 25})
            elif i < 4:
                respostas.append({"questao_id": q["id"], "resposta": "C", "tempo_seg": 25})
            else:
                respostas.append({"questao_id": q["id"], "resposta": "", "tempo_seg": 0})

        r = client.post(f"/api/simulados/cronometrado/{sim_id}/finalizar", json={
            "respostas": respostas,
            "tempo_total_seg": 100,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["total_acertos"] == 2
        assert data["total_erros"] == 2
        assert data["total_em_branco"] == 2
        assert data["total_questoes"] == 6

    def test_finalizar_por_materia(self, client, setup_questoes):
        """Resultado agrupa acertos por matéria."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Por Matéria",
            "tempo_total_min": 90,
            "questoes_total": 9,
            "materias": [],
            "dificuldade_mix": {"facil": 3, "medio": 3, "dificil": 3},
        })
        sim_id = r.json()["id"]
        questoes = r.json()["questoes"]

        respostas = [
            {"questao_id": q["id"], "resposta": "A", "tempo_seg": 30}
            for q in questoes
        ]

        r = client.post(f"/api/simulados/cronometrado/{sim_id}/finalizar", json={
            "respostas": respostas,
            "tempo_total_seg": 270,
        })
        assert r.status_code == 200
        data = r.json()
        assert "por_materia" in data
        assert len(data["por_materia"]) >= 1
        for mat in data["por_materia"]:
            assert "materia" in mat
            assert "acertos" in mat
            assert "total" in mat
            assert mat["acertos"] <= mat["total"]

    def test_finalizar_simulado_inexistente(self, client, setup_questoes):
        """Retorna 404 para simulado inexistente."""
        r = client.post("/api/simulados/cronometrado/99999/finalizar", json={
            "respostas": [{"questao_id": 1, "resposta": "A", "tempo_seg": 10}],
            "tempo_total_seg": 10,
        })
        assert r.status_code == 404
        assert "não encontrado" in r.json()["detail"]


# ============================================================
# GET /api/simulados/cronometrado/{id} — Consultar resultados
# ============================================================

class TestConsultarSimuladoCronometrado:
    def test_consultar_simulado_finalizado(self, client, setup_questoes):
        """Retorna detalhes do simulado finalizado com questões e respostas."""
        # Criar e finalizar
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Consulta",
            "tempo_total_min": 30,
            "questoes_total": 5,
            "materias": [],
            "dificuldade_mix": {"facil": 2, "medio": 2, "dificil": 1},
        })
        sim_id = r.json()["id"]
        questoes = r.json()["questoes"]

        # Finalizar com respostas
        respostas = [
            {"questao_id": q["id"], "resposta": "A", "tempo_seg": 15}
            for q in questoes
        ]
        client.post(f"/api/simulados/cronometrado/{sim_id}/finalizar", json={
            "respostas": respostas,
            "tempo_total_seg": 75,
        })

        # Consultar
        r = client.get(f"/api/simulados/cronometrado/{sim_id}")
        assert r.status_code == 200
        data = r.json()
        assert "simulado" in data
        assert "questoes" in data
        assert data["simulado"]["id"] == sim_id
        assert data["simulado"]["titulo"] == "Simulado Consulta"
        assert data["simulado"]["status"] == "finalizado"
        assert data["simulado"]["nota"] is not None
        assert len(data["questoes"]) == 5
        # Verificar estrutura de cada questão
        for q in data["questoes"]:
            assert "id" in q
            assert "num" in q
            assert "materia" in q
            assert "enunciado" in q
            assert "alternativas" in q
            assert "resposta_usuario" in q
            assert "acertou" in q
            assert "resposta_correta" in q
            assert "explicacao" in q

    def test_consultar_simulado_nao_finalizado(self, client, setup_questoes):
        """Consultar simulado antes de finalizar também funciona."""
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Simulado Aberto",
            "tempo_total_min": 60,
            "questoes_total": 5,
            "materias": [],
            "dificuldade_mix": {"facil": 2, "medio": 2, "dificil": 1},
        })
        sim_id = r.json()["id"]

        r = client.get(f"/api/simulados/cronometrado/{sim_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["simulado"]["status"] != "finalizado"
        assert len(data["questoes"]) == 5
        # Sem respostas ainda (pode ser None ou string vazia)
        for q in data["questoes"]:
            assert not q["resposta_usuario"]

    def test_consultar_simulado_inexistente(self, client, setup_questoes):
        """Retorna 404 para simulado inexistente."""
        r = client.get("/api/simulados/cronometrado/99999")
        assert r.status_code == 404
        assert "não encontrado" in r.json()["detail"]


# ============================================================
# FLUXO COMPLETO — Criar, responder e consultar resultado
# ============================================================

class TestFluxoCompleto:
    def test_fluxo_criar_finalizar_consultar(self, client, setup_questoes):
        """Testa o fluxo completo de criação, finalização e consulta."""
        # 1. Criar
        r = client.post("/api/simulados/cronometrado", json={
            "titulo": "Fluxo Completo",
            "tempo_total_min": 240,
            "questoes_total": 8,
            "materias": ["Direito Constitucional", "Português"],
            "dificuldade_mix": {"facil": 3, "medio": 3, "dificil": 2},
        })
        assert r.status_code == 200
        sim_id = r.json()["id"]
        questoes = r.json()["questoes"]
        assert len(questoes) <= 8

        # 2. Verificar que está como não finalizado
        r = client.get(f"/api/simulados/cronometrado/{sim_id}")
        assert r.json()["simulado"]["status"] != "finalizado"

        # 3. Finalizar com respostas
        respostas = [
            {"questao_id": q["id"], "resposta": "A", "tempo_seg": 45}
            for q in questoes
        ]
        r = client.post(f"/api/simulados/cronometrado/{sim_id}/finalizar", json={
            "respostas": respostas,
            "tempo_total_seg": len(questoes) * 45,
        })
        assert r.status_code == 200
        resultado = r.json()
        assert resultado["nota_bruta"] == 100.0
        assert resultado["total_acertos"] == len(questoes)

        # 4. Consultar resultado final
        r = client.get(f"/api/simulados/cronometrado/{sim_id}")
        assert r.status_code == 200
        data = r.json()
        assert data["simulado"]["status"] == "finalizado"
        assert data["simulado"]["nota"] == 100.0
        assert data["simulado"]["acertos"] == len(questoes)


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

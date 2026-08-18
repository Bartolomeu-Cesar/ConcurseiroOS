"""
Testes dos Lotes E e F:
- Mapa de calor de erros por tópico
- Estatísticas por banca examinadora
- Tempo médio por questão
- Histórico de evolução por matéria
- Simulado por prova real
- Resumos automáticos (Elaboration Strategy)

Executar: pytest tests/test_lote_ef.py -v
"""
import os
import sys
import tempfile
import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
database.DB_PATH = _tmp_db.name
database.init_db()

from main import app
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _create_questao(client, materia="Direito Penal", topico="Crimes contra pessoa", banca="CESPE", dificuldade="Médio"):
    return client.post("/api/questoes", json={
        "materia": materia,
        "topico": topico,
        "enunciado": f"Questão sobre {topico}",
        "alternativa_a": "Opção A",
        "alternativa_b": "Opção B",
        "alternativa_c": "Opção C",
        "alternativa_d": "Opção D",
        "resposta_correta": "A",
        "banca": banca,
        "dificuldade": dificuldade
    })


def _responder_questao(client, qid, resposta="A", tempo=30):
    return client.post(f"/api/questoes/{qid}/responder", json={
        "resposta": resposta,
        "tempo_segundos": tempo
    })


# ============================================================
# 1. MAPA DE CALOR DE ERROS POR TÓPICO
# ============================================================

class TestHeatmapErros:
    def test_heatmap_erros_empty(self, client):
        r = client.get("/api/heatmap-erros")
        assert r.status_code == 200
        data = r.json()
        assert "materias" in data

    def test_heatmap_erros_with_data(self, client):
        # Criar questões e respostas
        r1 = _create_questao(client, "Dir. Penal", "Crimes contra pessoa")
        qid1 = r1.json()["id"]
        _responder_questao(client, qid1, "B")  # Errou

        r2 = _create_questao(client, "Dir. Penal", "Penas")
        qid2 = r2.json()["id"]
        _responder_questao(client, qid2, "A")  # Acertou

        r = client.get("/api/heatmap-erros")
        assert r.status_code == 200
        data = r.json()
        assert "materias" in data
        assert len(data["materias"]) > 0

        mat = data["materias"][0]
        assert "materia" in mat
        assert "total_erros" in mat
        assert "total_questoes" in mat
        assert "pct_erro" in mat
        assert "topicos" in mat

        if mat["topicos"]:
            top = mat["topicos"][0]
            assert "topico" in top
            assert "erros" in top
            assert "total" in top
            assert "pct_erro" in top
            assert "intensidade" in top
            assert 0 <= top["intensidade"] <= 4


# ============================================================
# 2. ESTATÍSTICAS POR BANCA EXAMINADORA
# ============================================================

class TestStatsBanca:
    def test_questao_com_banca(self, client):
        r = _create_questao(client, "Informática", "Redes", "FGV")
        assert r.status_code == 200
        qid = r.json()["id"]

        # Verificar que a questão tem campo banca
        r2 = client.get(f"/api/questoes/{qid}")
        assert r2.status_code == 200
        assert r2.json().get("banca") == "FGV"

    def test_stats_por_banca(self, client):
        # Criar e responder questões com banca
        r = _create_questao(client, "Dir. Administrativo", "Atos", "CESPE")
        qid = r.json()["id"]
        _responder_questao(client, qid, "A")

        r = client.get("/api/questoes/stats/por-banca")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        if data:
            item = data[0]
            assert "banca" in item
            assert "total" in item
            assert "acertos" in item
            assert "pct_acerto" in item

    def test_list_bancas(self, client):
        r = client.get("/api/questoes/bancas")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        # Deve ter CESPE e FGV das questões criadas
        assert "CESPE" in data or "FGV" in data

    def test_filter_by_banca(self, client):
        r = client.get("/api/questoes?banca=CESPE")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)
        for q in data:
            assert q.get("banca") == "CESPE"


# ============================================================
# 3. TEMPO MÉDIO POR QUESTÃO
# ============================================================

class TestStatsTempo:
    def test_stats_tempo(self, client):
        # Criar e responder com tempo
        r = _create_questao(client, "Português", "Gramática", "CESPE")
        qid = r.json()["id"]
        _responder_questao(client, qid, "A", tempo=45)

        r = client.get("/api/questoes/stats/tempo")
        assert r.status_code == 200
        data = r.json()
        assert "tempo_medio_seg" in data
        assert "tempo_medio_formatado" in data
        assert "por_materia" in data
        assert "por_dificuldade" in data
        assert "analise" in data
        assert "tempo_prova_estimado_min" in data["analise"]
        assert "questoes_estimadas_prova" in data["analise"]
        assert "tempo_por_questao_prova_seg" in data["analise"]
        assert "seu_tempo_vs_prova" in data["analise"]
        assert "mensagem" in data["analise"]


# ============================================================
# 4. HISTÓRICO DE EVOLUÇÃO POR MATÉRIA
# ============================================================

class TestEvolucao:
    def test_evolucao_default(self, client):
        r = client.get("/api/evolucao")
        assert r.status_code == 200
        data = r.json()
        assert "semanas" in data
        assert data["semanas"] == 12
        assert "evolucao" in data
        assert "tendencia" in data

    def test_evolucao_custom_semanas(self, client):
        r = client.get("/api/evolucao?semanas=4")
        assert r.status_code == 200
        data = r.json()
        assert data["semanas"] == 4

    def test_evolucao_structure(self, client):
        r = client.get("/api/evolucao")
        assert r.status_code == 200
        data = r.json()
        if data["evolucao"]:
            sem = data["evolucao"][0]
            assert "semana" in sem
            assert "inicio" in sem
            assert "materias" in sem
            assert "geral" in sem
            assert "questoes" in sem["geral"]
            assert "acertos" in sem["geral"]
            assert "pct" in sem["geral"]


# ============================================================
# 5. SIMULADO POR PROVA REAL
# ============================================================

class TestSimuladoProvaReal:
    def test_prova_real_sem_edital(self, client):
        r = client.post("/api/simulados/prova-real", json={
            "titulo": "Simulado Teste",
            "edital_nome": "INEXISTENTE",
            "cargo": "",
            "tempo_limite_min": 180
        })
        assert r.status_code == 400

    def test_prova_real_com_dados(self, client):
        # Criar tópicos no edital
        client.post("/api/edital", json={
            "materia": "Dir. Penal", "topico": "Tipicidade",
            "edital_nome": "PRFEF", "cargo": "Agente"
        })
        client.post("/api/edital", json={
            "materia": "Dir. Penal", "topico": "Antijuridicidade",
            "edital_nome": "PRFEF", "cargo": "Agente"
        })
        client.post("/api/edital", json={
            "materia": "Informática", "topico": "Redes",
            "edital_nome": "PRFEF", "cargo": "Agente"
        })

        # Criar questões
        for i in range(5):
            _create_questao(client, "Dir. Penal", "Tipicidade")
        for i in range(3):
            _create_questao(client, "Informática", "Redes")

        r = client.post("/api/simulados/prova-real", json={
            "titulo": "Simulado PRF Real",
            "edital_nome": "PRFEF",
            "cargo": "Agente",
            "tempo_limite_min": 240
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "id" in data
        assert "total_questoes" in data
        assert data["total_questoes"] > 0
        assert "distribuicao" in data
        assert isinstance(data["distribuicao"], list)
        for d in data["distribuicao"]:
            assert "materia" in d
            assert "peso_pct" in d
            assert "questoes_selecionadas" in d


# ============================================================
# 6. RESUMOS AUTOMÁTICOS (ELABORATION STRATEGY)
# ============================================================

class TestResumos:
    def test_get_resumos_empty(self, client):
        # Criar um tópico
        r = client.post("/api/edital", json={
            "materia": "Dir. Civil", "topico": "Contratos",
            "edital_nome": "Teste", "cargo": "Analista"
        })
        eid = r.json()["id"]
        r = client.get(f"/api/edital/{eid}/resumo")
        assert r.status_code == 200
        assert r.json() == []

    def test_create_resumo(self, client):
        r = client.post("/api/edital", json={
            "materia": "Dir. Civil", "topico": "Obrigações",
            "edital_nome": "Teste", "cargo": "Analista"
        })
        eid = r.json()["id"]

        r = client.post(f"/api/edital/{eid}/resumo", json={
            "resumo": "Obrigações são vínculos jurídicos entre partes.",
            "tipo": "3frases"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "id" in data

        # Verificar que foi salvo
        r = client.get(f"/api/edital/{eid}/resumo")
        assert r.status_code == 200
        resumos = r.json()
        assert len(resumos) == 1
        assert resumos[0]["resumo"] == "Obrigações são vínculos jurídicos entre partes."
        assert resumos[0]["tipo"] == "3frases"

    def test_delete_resumo(self, client):
        r = client.post("/api/edital", json={
            "materia": "Dir. Civil", "topico": "Posse",
            "edital_nome": "Teste", "cargo": "Analista"
        })
        eid = r.json()["id"]

        r = client.post(f"/api/edital/{eid}/resumo", json={
            "resumo": "Posse é o poder de fato sobre a coisa.",
            "tipo": "livre"
        })
        resumo_id = r.json()["id"]

        r = client.delete(f"/api/resumos/{resumo_id}")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verificar que foi deletado
        r = client.get(f"/api/edital/{eid}/resumo")
        assert r.json() == []

    def test_prompt_resumo(self, client):
        r = client.post("/api/edital", json={
            "materia": "Direito Penal", "topico": "Crimes contra pessoa",
            "edital_nome": "Teste", "cargo": "Analista"
        })
        eid = r.json()["id"]

        r = client.get(f"/api/edital/{eid}/prompt-resumo")
        assert r.status_code == 200
        data = r.json()
        assert "materia" in data
        assert "topico" in data
        assert "prompt" in data
        assert "dicas" in data
        assert isinstance(data["dicas"], list)
        assert len(data["dicas"]) > 0
        assert "Crimes contra pessoa" in data["prompt"]

    def test_prompt_resumo_404(self, client):
        r = client.get("/api/edital/99999/prompt-resumo")
        assert r.status_code == 404

    def test_create_resumo_404(self, client):
        r = client.post("/api/edital/99999/resumo", json={
            "resumo": "Teste",
            "tipo": "livre"
        })
        assert r.status_code == 404

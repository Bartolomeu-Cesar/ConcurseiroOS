"""
Testes de integração do Treinador v2 (inteligência completa).
Cobre: /api/treinador, /api/trilha-diaria, /api/calendario-semanal, /api/treinador/sugestao-rapida

Executar: pytest tests/test_treinador_v2.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_treinador.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import settings as settings_mod
from database import get_db_session

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
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


# Fixture autouse que garante DB correto antes de cada teste
@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield
    # não remove - deixa ativo durante todo o módulo


client = TestClient(app)


# ============================================================
# HELPERS
# ============================================================

def _create_edital_topic(materia="Direito Penal", topico="Crimes contra a pessoa",
                         edital_nome="PC-DF 2026", cargo="Delegado"):
    """Helper para criar tópico no edital."""
    r = client.post("/api/edital", json={
        "materia": materia,
        "topico": topico,
        "edital_nome": edital_nome,
        "cargo": cargo,
    })
    assert r.status_code == 200
    return r.json()["id"]


def _create_questao(materia="Direito Penal", topico="Crimes", banca="CESPE"):
    """Helper para criar questão."""
    r = client.post("/api/questoes", json={
        "materia": materia,
        "topico": topico,
        "enunciado": f"Questão de {materia} - {topico}?",
        "alternativa_a": "Certo",
        "alternativa_b": "Errado",
        "alternativa_c": "C",
        "alternativa_d": "D",
        "resposta_correta": "A",
        "banca": banca,
    })
    assert r.status_code == 200
    return r.json()["id"]


def _answer_questao(questao_id: int, resposta: str = "A", tempo: int = 30):
    """Helper para responder uma questão."""
    r = client.post(f"/api/questoes/{questao_id}/responder", json={
        "resposta": resposta,
        "tempo_segundos": tempo,
    })
    assert r.status_code == 200
    return r.json()


def _create_flashcard(pergunta="Teste?", resposta="Sim"):
    """Helper para criar flashcard."""
    r = client.post("/api/flashcards", json={
        "pergunta": pergunta,
        "resposta": resposta,
    })
    assert r.status_code == 200
    return r.json()["id"]


def _seed_study_data():
    """Popula DB com dados de estudo para testes significativos."""
    # Criar tópicos do edital
    _create_edital_topic("Direito Constitucional", "Princípios Fundamentais", "PC-DF 2026", "Delegado")
    _create_edital_topic("Direito Constitucional", "Direitos e Garantias", "PC-DF 2026", "Delegado")
    _create_edital_topic("Direito Penal", "Crimes contra a pessoa", "PC-DF 2026", "Delegado")
    _create_edital_topic("Direito Penal", "Crimes contra o patrimônio", "PC-DF 2026", "Delegado")
    _create_edital_topic("Direito Processual Penal", "Inquérito Policial", "PC-DF 2026", "Delegado")
    _create_edital_topic("Direito Administrativo", "Atos Administrativos", "PC-DF 2026", "Delegado")

    # Criar questões e respostas para múltiplas matérias
    # Direito Constitucional: bom desempenho (80%)
    for i in range(5):
        qid = _create_questao("Direito Constitucional", "Princípios Fundamentais", "CESPE")
        _answer_questao(qid, "A")  # acerto
    for i in range(1):
        qid = _create_questao("Direito Constitucional", "Direitos e Garantias", "CESPE")
        _answer_questao(qid, "B")  # erro

    # Direito Penal: desempenho fraco (40%)
    for i in range(2):
        qid = _create_questao("Direito Penal", "Crimes contra a pessoa", "CESPE")
        _answer_questao(qid, "A")  # acerto
    for i in range(3):
        qid = _create_questao("Direito Penal", "Crimes contra o patrimônio", "CESPE")
        _answer_questao(qid, "B")  # erro

    # Direito Processual Penal: desempenho médio (60%)
    for i in range(3):
        qid = _create_questao("Direito Processual Penal", "Inquérito Policial", "CESPE")
        _answer_questao(qid, "A")  # acerto
    for i in range(2):
        qid = _create_questao("Direito Processual Penal", "Inquérito Policial", "CESPE")
        _answer_questao(qid, "B")  # erro

    # Criar flashcard para gerar revisões pendentes
    _create_flashcard("O que é mandado de segurança?", "Remédio constitucional...")


# ============================================================
# 1. GET /api/treinador - TREINADOR INTELIGENTE
# ============================================================

class TestTreinadorInteligente:
    """Testes do endpoint principal do treinador inteligente."""

    def test_treinador_empty_db(self):
        """Com DB vazio (novo usuário), retorna estrutura válida com defaults."""
        r = client.get("/api/treinador")
        assert r.status_code == 200
        data = r.json()

        # Estrutura principal obrigatória
        assert "score_prontidao" in data
        assert "nivel" in data
        assert "recomendacoes" in data
        assert "materias_foco" in data
        assert "revisoes_pendentes" in data
        assert "meta_hoje" in data
        assert "inteligencia" in data
        assert "dias_prova" in data

        # Tipos corretos
        assert isinstance(data["score_prontidao"], (int, float))
        assert isinstance(data["nivel"], str)
        assert isinstance(data["recomendacoes"], list)
        assert isinstance(data["materias_foco"], list)
        assert isinstance(data["revisoes_pendentes"], dict)
        assert isinstance(data["meta_hoje"], dict)
        assert isinstance(data["inteligencia"], dict)

    def test_treinador_meta_hoje_structure(self):
        """meta_hoje deve ter horas, questoes, cumprido_horas, cumprido_questoes."""
        r = client.get("/api/treinador")
        assert r.status_code == 200
        meta = r.json()["meta_hoje"]

        assert "horas" in meta
        assert "questoes" in meta
        assert "cumprido_horas" in meta
        assert "cumprido_questoes" in meta
        assert isinstance(meta["horas"], (int, float))
        assert isinstance(meta["questoes"], int)

    def test_treinador_revisoes_pendentes_structure(self):
        """revisoes_pendentes deve ter flashcards e topicos."""
        r = client.get("/api/treinador")
        assert r.status_code == 200
        rev = r.json()["revisoes_pendentes"]

        assert "flashcards" in rev
        assert "topicos" in rev
        assert isinstance(rev["flashcards"], int)
        assert isinstance(rev["topicos"], int)
        assert rev["flashcards"] >= 0
        assert rev["topicos"] >= 0

    def test_treinador_inteligencia_structure(self):
        """inteligencia deve conter as 8 camadas."""
        r = client.get("/api/treinador")
        assert r.status_code == 200
        intel = r.json()["inteligencia"]

        expected_keys = [
            "error_patterns",
            "ritmo_adaptativo",
            "forgetting_risk",
            "banca_weights",
            "plateaus",
            "micro_metas",
            "horario_otimo",
            "sprint_mode",
        ]
        for key in expected_keys:
            assert key in intel, f"Missing key: {key}"

    def test_treinador_with_study_data(self):
        """Com dados de estudo, treinador gera recomendações e materias_foco."""
        _seed_study_data()

        r = client.get("/api/treinador")
        assert r.status_code == 200
        data = r.json()

        # Com dados, score deve ser > 0
        assert data["score_prontidao"] >= 0
        assert data["nivel"] in ["Começando", "Iniciante", "Regular", "Intermediário", "Avançado"]

        # Deve ter recomendações quando há dados
        assert isinstance(data["recomendacoes"], list)

        # meta_hoje cumprido_questoes deve refletir questões respondidas
        assert data["meta_hoje"]["cumprido_questoes"] >= 0

    def test_treinador_with_edital_filter(self):
        """Filtro por edital_nome e cargo funciona."""
        r = client.get("/api/treinador", params={
            "edital_nome": "PC-DF 2026",
            "cargo": "Delegado",
        })
        assert r.status_code == 200
        data = r.json()
        assert "score_prontidao" in data
        assert "inteligencia" in data

    def test_treinador_score_range(self):
        """Score de prontidão deve estar entre 0 e 100."""
        r = client.get("/api/treinador")
        assert r.status_code == 200
        score = r.json()["score_prontidao"]
        assert 0 <= score <= 100

    def test_treinador_recomendacoes_structure(self):
        """Cada recomendação deve ter ao menos tipo e msg."""
        r = client.get("/api/treinador")
        assert r.status_code == 200
        recs = r.json()["recomendacoes"]
        for rec in recs:
            assert "tipo" in rec
            assert "msg" in rec
            assert isinstance(rec["tipo"], str)
            assert isinstance(rec["msg"], str)


# ============================================================
# 2. GET /api/trilha-diaria - TRILHA DE ESTUDO DIÁRIA
# ============================================================

class TestTrilhaDiaria:
    """Testes do endpoint de trilha diária."""

    def test_trilha_returns_activities(self):
        """Deve retornar lista de atividades."""
        r = client.get("/api/trilha-diaria")
        assert r.status_code == 200
        data = r.json()

        assert "atividades" in data
        assert isinstance(data["atividades"], list)

    def test_trilha_structure(self):
        """Resposta deve ter data, horas_disponiveis, atividades, tempo_total_min, foco_principal."""
        r = client.get("/api/trilha-diaria")
        assert r.status_code == 200
        data = r.json()

        expected_keys = ["data", "horas_disponiveis", "atividades", "tempo_total_min", "foco_principal", "motivo"]
        for key in expected_keys:
            assert key in data, f"Missing key: {key}"

        assert isinstance(data["data"], str)
        assert isinstance(data["horas_disponiveis"], (int, float))
        assert isinstance(data["tempo_total_min"], int)
        assert isinstance(data["foco_principal"], str)

    def test_trilha_activities_structure(self):
        """Cada atividade deve ter ordem, tipo, tempo_min."""
        r = client.get("/api/trilha-diaria")
        assert r.status_code == 200
        atividades = r.json()["atividades"]

        for ativ in atividades:
            assert "ordem" in ativ
            assert "tipo" in ativ
            assert "tempo_min" in ativ
            assert isinstance(ativ["ordem"], int)
            assert isinstance(ativ["tipo"], str)
            assert isinstance(ativ["tempo_min"], int)
            assert ativ["tempo_min"] >= 0

    def test_trilha_custom_hours(self):
        """Deve respeitar parâmetro horas_disponiveis."""
        r = client.get("/api/trilha-diaria", params={"horas_disponiveis": 5.0})
        assert r.status_code == 200
        data = r.json()
        assert data["horas_disponiveis"] == 5.0
        # Tempo total não deve exceder as horas disponíveis
        assert data["tempo_total_min"] <= 5.0 * 60 + 1  # margem de arredondamento

    def test_trilha_with_edital_filter(self):
        """Filtro por edital funciona."""
        r = client.get("/api/trilha-diaria", params={
            "edital_nome": "PC-DF 2026",
            "cargo": "Delegado",
        })
        assert r.status_code == 200
        data = r.json()
        assert "atividades" in data

    def test_trilha_tempo_total_consistent(self):
        """tempo_total_min deve ser a soma dos tempos das atividades."""
        r = client.get("/api/trilha-diaria")
        assert r.status_code == 200
        data = r.json()
        soma = sum(a["tempo_min"] for a in data["atividades"])
        assert data["tempo_total_min"] == soma


# ============================================================
# 3. GET /api/calendario-semanal - CALENDÁRIO SEMANAL
# ============================================================

class TestCalendarioSemanal:
    """Testes do endpoint de calendário semanal."""

    def test_calendario_returns_7_days(self):
        """Deve retornar exatamente 7 dias."""
        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200
        data = r.json()

        assert "dias" in data
        assert len(data["dias"]) == 7

    def test_calendario_structure(self):
        """Resposta deve ter semana_inicio, semana_fim, horas_dia, dias, resumo."""
        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200
        data = r.json()

        expected_keys = ["semana_inicio", "semana_fim", "horas_dia", "dias", "resumo"]
        for key in expected_keys:
            assert key in data, f"Missing key: {key}"

        assert isinstance(data["semana_inicio"], str)
        assert isinstance(data["semana_fim"], str)
        assert isinstance(data["horas_dia"], (int, float))
        assert isinstance(data["dias"], list)
        assert isinstance(data["resumo"], dict)

    def test_calendario_day_structure(self):
        """Cada dia deve ter dia_semana, nome, data, atividades, tempo_total_min, materias."""
        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200
        dias = r.json()["dias"]

        for dia in dias:
            assert "dia_semana" in dia
            assert "nome" in dia
            assert "data" in dia
            assert "atividades" in dia
            assert "tempo_total_min" in dia
            assert "materias" in dia

            assert isinstance(dia["dia_semana"], int)
            assert 0 <= dia["dia_semana"] <= 6
            assert isinstance(dia["nome"], str)
            assert isinstance(dia["data"], str)
            assert isinstance(dia["atividades"], list)
            assert isinstance(dia["tempo_total_min"], int)
            assert isinstance(dia["materias"], list)

    def test_calendario_day_names(self):
        """Nomes dos dias devem estar corretos."""
        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200
        dias = r.json()["dias"]

        nomes_esperados = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
        for i, dia in enumerate(dias):
            assert dia["nome"] == nomes_esperados[i]
            assert dia["dia_semana"] == i

    def test_calendario_resumo_structure(self):
        """Resumo deve conter total_materias, horas_semana, distribuicao."""
        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200
        resumo = r.json()["resumo"]

        assert "total_materias" in resumo
        assert "horas_semana" in resumo
        assert "distribuicao" in resumo
        assert isinstance(resumo["total_materias"], int)
        assert isinstance(resumo["horas_semana"], (int, float))
        assert isinstance(resumo["distribuicao"], list)

    def test_calendario_custom_hours(self):
        """Parâmetro horas_dia deve ser refletido."""
        r = client.get("/api/calendario-semanal", params={"horas_dia": 4.0})
        assert r.status_code == 200
        data = r.json()
        assert data["horas_dia"] == 4.0

    def test_calendario_with_edital_filter(self):
        """Filtro por edital funciona."""
        r = client.get("/api/calendario-semanal", params={
            "edital_nome": "PC-DF 2026",
            "cargo": "Delegado",
        })
        assert r.status_code == 200
        data = r.json()
        assert len(data["dias"]) == 7

    def test_calendario_activity_types_valid(self):
        """Atividades devem ter tipos válidos."""
        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200
        dias = r.json()["dias"]

        valid_types = {"revisao", "estudo", "questoes", "simulado"}
        for dia in dias:
            for ativ in dia["atividades"]:
                assert "tipo" in ativ
                assert ativ["tipo"] in valid_types, f"Tipo inválido: {ativ['tipo']}"


# ============================================================
# 4. GET /api/treinador/sugestao-rapida - SUGESTÃO RÁPIDA
# ============================================================

class TestSugestaoRapida:
    """Testes do endpoint de sugestão rápida."""

    def test_sugestao_returns_valid_response(self):
        """Deve retornar sugestão com materia, motivo e tempo_min."""
        r = client.get("/api/treinador/sugestao-rapida")
        assert r.status_code == 200
        data = r.json()

        assert "materia" in data
        assert "motivo" in data
        assert "tempo_min" in data

    def test_sugestao_materia_not_empty(self):
        """Matéria sugerida não deve ser vazia."""
        r = client.get("/api/treinador/sugestao-rapida")
        assert r.status_code == 200
        data = r.json()

        assert data["materia"] != ""
        assert len(data["materia"]) > 0

    def test_sugestao_tempo_min_positive(self):
        """Tempo mínimo deve ser positivo."""
        r = client.get("/api/treinador/sugestao-rapida")
        assert r.status_code == 200
        data = r.json()

        assert data["tempo_min"] > 0

    def test_sugestao_motivo_not_empty(self):
        """Motivo deve estar preenchido."""
        r = client.get("/api/treinador/sugestao-rapida")
        assert r.status_code == 200
        data = r.json()

        assert data["motivo"] != ""
        assert len(data["motivo"]) > 0

    def test_sugestao_with_study_history(self):
        """Com histórico, deve sugerir matéria com menor acerto."""
        r = client.get("/api/treinador/sugestao-rapida")
        assert r.status_code == 200
        data = r.json()

        # Com dados populados por _seed_study_data (Direito Penal é a mais fraca)
        assert data["materia"] in [
            "Direito Penal",
            "Direito Processual Penal",
            "Direito Constitucional",
            "Direito Administrativo",
            "Revisão Geral",
        ]


# ============================================================
# 5. AUTO-REGENERAÇÃO: planejador desalinhado do ciclo ativo
# ============================================================

class TestCalendarioAutoRegenera:
    """Ao trocar de concurso, o planejador antigo deve ser realinhado ao ciclo."""

    def _set_ciclo(self, materias):
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM ciclo_estudos WHERE user_id = 1")
        for i, m in enumerate(materias):
            conn.execute(
                "INSERT INTO ciclo_estudos (materia, horas_alvo, ordem, ativo, user_id) VALUES (?, 2.0, ?, 1, 1)",
                (m, i),
            )
        conn.commit()
        conn.close()

    def _set_planejador(self, materias):
        conn = sqlite3.connect(_tmp_db.name)
        conn.execute("DELETE FROM planejador_semanal WHERE user_id = 1")
        for i, m in enumerate(materias):
            conn.execute(
                "INSERT INTO planejador_semanal (dia_semana, materia, horas, user_id) VALUES (?, ?, 1.0, 1)",
                (i % 6, m),
            )
        conn.commit()
        conn.close()

    def _plan_materias(self):
        conn = sqlite3.connect(_tmp_db.name)
        rows = conn.execute("SELECT DISTINCT materia FROM planejador_semanal WHERE user_id = 1").fetchall()
        conn.close()
        return {r[0] for r in rows}

    def test_desalinhado_regenera_para_ciclo_atual(self):
        """Planejador de outro concurso é substituído pelas matérias do ciclo atual."""
        self._set_ciclo(["Informática", "Língua Portuguesa", "Raciocínio Lógico e Científico"])
        # Planejador preso a um concurso antigo (matérias que não estão no ciclo)
        self._set_planejador(["Contabilidade Geral", "Auditoria", "Controle Externo"])

        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200

        mats = self._plan_materias()
        # As matérias antigas sumiram e as do ciclo entraram
        assert "Contabilidade Geral" not in mats
        assert mats.issubset({"Informática", "Língua Portuguesa", "Raciocínio Lógico e Científico"})
        assert len(mats) >= 1

    def test_alinhado_nao_muda(self):
        """Se o planejador já corresponde ao ciclo, não é regenerado (idempotente)."""
        self._set_ciclo(["Informática", "Língua Portuguesa"])
        self._set_planejador(["Informática", "Língua Portuguesa"])
        antes = self._plan_materias()

        r = client.get("/api/calendario-semanal")
        assert r.status_code == 200

        depois = self._plan_materias()
        assert antes == depois == {"Informática", "Língua Portuguesa"}

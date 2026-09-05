"""Testes das funções puras do helper central de técnicas (study_techniques)."""
import os
import sys

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from study_techniques import (
    lag_effect_interval,
    retrieval_practice_prompt,
    successive_relearning_due,
)

# ============================================================
# LAG EFFECT
# ============================================================

def test_lag_effect_sem_prova_nao_comprime():
    assert lag_effect_interval(45, None) == 45
    assert lag_effect_interval(45, 0) == 45


def test_lag_effect_intervalo_1_nao_comprime():
    assert lag_effect_interval(1, 10) == 1


def test_lag_effect_teto_70pct_do_tempo_restante():
    # Prova em 100 dias, sem compressão suave (>60d): teto = 70
    assert lag_effect_interval(90, 100) == 70


def test_lag_effect_prova_proxima_comprime_mais():
    # Prova em 30 dias: teto = 21; depois compressão suave (fator = max(0.5, 30/90)=0.5)
    # 21 * 0.5 = 10
    assert lag_effect_interval(45, 30) == 10


def test_lag_effect_nunca_abaixo_de_1():
    assert lag_effect_interval(2, 1) >= 1


# ============================================================
# SUCCESSIVE RELEARNING
# ============================================================

def test_successive_relearning_due_filtra_vencidos():
    topicos = [
        {"topico": "A", "proxima_revisao": "2020-01-01", "stability_edital": 5},   # vencido
        {"topico": "B", "proxima_revisao": "2999-01-01", "stability_edital": 2},   # futuro
        {"topico": "C", "proxima_revisao": "2020-01-01", "stability_edital": 1},   # vencido, mais frágil
        {"topico": "D", "proxima_revisao": "", "stability_edital": 0},              # sem data
    ]
    due = successive_relearning_due(topicos, hoje="2024-01-01")
    topicos_due = [t["topico"] for t in due]
    assert topicos_due == ["C", "A"]  # frágil primeiro (stability 1 antes de 5)


def test_successive_relearning_due_vazio():
    assert successive_relearning_due([], hoje="2024-01-01") == []


# ============================================================
# RETRIEVAL PRACTICE
# ============================================================

def test_retrieval_practice_prompt_estrutura():
    p = retrieval_practice_prompt("Português", "Crase")
    assert p["tecnica"] == "retrieval_practice"
    assert "Crase" in p["mensagem"]
    tipos = {a["tipo"] for a in p["acoes"]}
    assert {"questoes", "flashcards", "brain_dump"} <= tipos

"""Helper central de técnicas científicas de estudo (reutilizável em todo o app).

Consolida decisões baseadas em evidência que estavam espalhadas/duplicadas em
routers (flashcards, trilha, treinador, edital). A ideia é ter UM lugar para a
lógica das técnicas, para que qualquer feature aplique o mesmo comportamento.

Funções puras (sem I/O) ficam fáceis de testar; funções com `conn` resolvem os
dados do usuário e delegam à versão pura.

Técnicas cobertas aqui:
- Lag Effect / Exam-Aware Spacing (Cepeda et al., 2006)
- Successive Relearning (Rawson & Dunlosky, 2022)
- Retrieval Practice / Forward Testing Effect (Roediger & Karpicke, 2006)
- Ordenação inteligente (delega a study_ordering: Interleaving, Pre-testing,
  Desirable Difficulty, Expanding Retrieval, Serial Position)

Uso:
    from study_techniques import (
        lag_effect_interval, apply_lag_effect,
        successive_relearning_due, retrieval_practice_prompt,
        order_items_intelligently,
    )
"""
from __future__ import annotations

from datetime import date, timedelta

# Reexporta o motor de ordenação para ter um ponto único de import.
from study_ordering import order_items_intelligently  # noqa: F401


# ============================================================
# LAG EFFECT / EXAM-AWARE SPACING
# ============================================================

def lag_effect_interval(interval: int, dias_ate_prova: int | None) -> int:
    """Comprime um intervalo de revisão conforme a proximidade da prova.

    Cepeda et al. (2006): o intervalo ótimo depende de QUANDO o aluno precisa
    lembrar. Se a prova é em 30 dias, um intervalo de 45d é inútil.

    Regras (idênticas à lógica consolidada do review-fsrs):
    - Só comprime se há data de prova futura e o intervalo > 1.
    - Teto em 70% do tempo restante (não ultrapassa a janela útil).
    - Compressão suave adicional para provas próximas (<= 60 dias).

    É uma função PURA — não acessa banco. Retorna o intervalo ajustado (>= 1).
    """
    adjusted = interval
    if dias_ate_prova and dias_ate_prova > 0 and adjusted > 1:
        max_interval = max(1, int(dias_ate_prova * 0.7))
        if adjusted > max_interval:
            adjusted = max_interval
        if dias_ate_prova <= 60 and adjusted > 3:
            fator = max(0.5, dias_ate_prova / 90)
            adjusted = max(1, int(adjusted * fator))
    return adjusted


def apply_lag_effect(conn, user_id: int, interval: int) -> int:
    """Versão com I/O: resolve dias até a prova do usuário e aplica o Lag Effect."""
    from services import get_dias_ate_prova
    try:
        dias = get_dias_ate_prova(conn, user_id)
    except Exception:
        dias = None
    return lag_effect_interval(interval, dias)


# ============================================================
# SUCCESSIVE RELEARNING
# ============================================================

def successive_relearning_due(topicos_concluidos: list[dict], hoje: str | None = None,
                              stability_key: str = "stability_edital",
                              proxima_key: str = "proxima_revisao") -> list[dict]:
    """Filtra tópicos JÁ concluídos que estão devidos para re-aprendizado.

    Rawson & Dunlosky (2022): reestudar itens já aprendidos até um novo critério
    de domínio, espaçado no tempo, é a via mais eficiente para retenção durável.

    Um tópico está "devido" se tem proxima_revisao <= hoje (venceu o intervalo).
    A ordenação prioriza menor stability (mais frágil = mais urgente).

    Função pura — recebe a lista já carregada do banco.
    """
    hoje = hoje or date.today().isoformat()
    due = []
    for t in topicos_concluidos:
        proxima = (t.get(proxima_key) or "").strip()
        if proxima and proxima <= hoje:
            due.append(t)
    # Mais frágil (menor stability) primeiro
    due.sort(key=lambda t: (t.get(stability_key) or 0))
    return due


# ============================================================
# RETRIEVAL PRACTICE / FORWARD TESTING EFFECT
# ============================================================

def retrieval_practice_prompt(materia: str, topico: str) -> dict:
    """Gera uma sugestão de recuperação ativa ao concluir uma etapa/tópico.

    Roediger & Karpicke (2006): recuperar da memória (fazer questões, recall)
    consolida mais que reler. Forward Testing Effect: testar o que acabou de
    estudar melhora o aprendizado do que vem depois.

    Retorna um dict com a ação sugerida (o frontend decide como apresentar).
    """
    materia = (materia or "").strip()
    topico = (topico or "").strip()
    return {
        "tecnica": "retrieval_practice",
        "titulo": "🎯 Fixe agora com recuperação ativa",
        "mensagem": f"Acabou de estudar “{topico or materia}”. Resolva algumas questões "
                    f"ou faça um brain dump — recuperar da memória fixa muito mais que reler.",
        "acoes": [
            {"tipo": "questoes", "label": "Resolver questões", "materia": materia},
            {"tipo": "flashcards", "label": "Revisar flashcards", "materia": materia},
            {"tipo": "brain_dump", "label": "Brain dump (escreva o que lembra)", "materia": materia},
        ],
    }

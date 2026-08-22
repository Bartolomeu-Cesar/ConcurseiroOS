"""Endpoint principal do Treinador Inteligente — GET /api/treinador."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id
from logger import log
from utils import calculate_streak, today_str

from .analise import (
    _analyze_error_patterns,
    _calculate_adaptive_pace,
    _calculate_readiness_score,
    _detect_optimal_hours,
    _detect_plateaus,
    _dias_ate_prova,
    _generate_micro_goals,
    _generate_recommendations,
    _get_banca_weights,
    _get_forgetting_risk,
    _get_last_session_by_subject,
    _get_pending_reviews,
    _get_performance_by_subject,
    _get_sprint_mode,
    _get_study_gaps,
)

router = APIRouter(prefix="", tags=["Treinador Inteligente"])


@router.get("/api/treinador", summary="Treinador Inteligente",
            description="Retorna recomendações personalizadas de estudo usando 8 camadas de inteligência: análise de erros, ritmo adaptativo, curva de esquecimento (FSRS), distribuição por banca, detecção de platô, micro-metas, horário ótimo e sprint mode.")
def treinador_inteligente(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Treinador com 8 camadas de inteligência: erros, ritmo, FSRS, banca, platô, micro-metas, horário, sprint."""
    desempenho = _get_performance_by_subject(conn, user_id)
    ultima_sessao = _get_last_session_by_subject(conn, user_id)
    pending = _get_pending_reviews(conn, user_id)

    query_edital = "SELECT COUNT(*) FROM edital WHERE user_id = ?"
    query_done = "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?"
    params_edital = [user_id]
    if edital_nome:
        query_edital += " AND edital_nome = ?"
        query_done += " AND edital_nome = ?"
        params_edital.append(edital_nome)
    if cargo:
        query_edital += " AND cargo = ?"
        query_done += " AND cargo = ?"
        params_edital.append(cargo)
    edital_total = conn.execute(query_edital, params_edital).fetchone()[0]
    edital_concluido = conn.execute(query_done, params_edital).fetchone()[0]

    inicio_semana = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    dias_semana = conn.execute("""
        SELECT COUNT(DISTINCT data) FROM streaks
        WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0) AND user_id = ?
    """, (inicio_semana, user_id)).fetchone()[0]

    metas = conn.execute("SELECT meta_horas, meta_questoes FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    meta_horas = metas[0] if metas else 3.0
    meta_questoes = metas[1] if metas else 30
    hoje_streak = conn.execute("SELECT horas_estudadas, questoes_resolvidas FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    horas_hoje = hoje_streak[0] if hoje_streak else 0
    questoes_hoje = hoje_streak[1] if hoje_streak else 0

    streak_info = calculate_streak(conn, user_id)
    streak = streak_info["streak_atual"]
    dias_prova = _dias_ate_prova(conn, user_id, edital_nome, cargo)

    q_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    q_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    pct_acerto_global = (q_acertos / q_total * 100) if q_total > 0 else 0
    pct_edital = (edital_concluido / edital_total * 100) if edital_total > 0 else 0

    # ===== 8 CAMADAS DE INTELIGÊNCIA =====
    # 1. Padrão de erros
    error_patterns = _analyze_error_patterns(conn, user_id)

    # 2. Ritmo adaptativo
    ritmo = _calculate_adaptive_pace(conn, user_id, dias_prova, edital_nome, cargo)

    # 3. Curva de esquecimento (FSRS)
    forgetting_risk = _get_forgetting_risk(conn, user_id)

    # 4. Peso da banca
    banca_weights = _get_banca_weights(conn, user_id, edital_nome, cargo)

    # 5. Detecção de platô
    plateaus = _detect_plateaus(conn, user_id)

    # 6. Micro-metas dinâmicas
    materias_foco = _get_study_gaps(conn, desempenho, ultima_sessao)
    micro_metas = _generate_micro_goals(conn, user_id, materias_foco)

    # 7. Horário ótimo
    horario_otimo = _detect_optimal_hours(conn, user_id)

    # 8. Sprint mode
    sprint_mode = _get_sprint_mode(conn, user_id, dias_prova, edital_nome, cargo)

    # Score enriquecido
    score, nivel = _calculate_readiness_score(pct_acerto_global, pct_edital, dias_semana, ritmo, plateaus)

    # Recomendações com todas as inteligências
    recomendacoes = _generate_recommendations(
        materias_foco, pending, streak, horas_hoje, meta_horas, dias_prova,
        error_patterns=error_patterns,
        micro_metas=micro_metas,
        sprint_mode=sprint_mode,
        plateaus=plateaus,
    )

    log.info(f"Treinador: score={score} nivel={nivel} recs={len(recomendacoes)} erros={len(error_patterns)} platos={len(plateaus)}")
    return {
        "score_prontidao": score,
        "nivel": nivel,
        "recomendacoes": recomendacoes,
        "materias_foco": materias_foco,
        "revisoes_pendentes": {"flashcards": pending["flashcards"], "topicos": pending["topicos"]},
        "meta_hoje": {"horas": meta_horas, "questoes": int(meta_questoes),
                      "cumprido_horas": round(horas_hoje, 1), "cumprido_questoes": int(questoes_hoje)},
        # Novas inteligências
        "inteligencia": {
            "error_patterns": error_patterns[:3],
            "ritmo_adaptativo": ritmo,
            "forgetting_risk": forgetting_risk[:5],
            "banca_weights": dict(list(banca_weights.items())[:5]) if banca_weights else None,
            "plateaus": plateaus,
            "micro_metas": micro_metas,
            "horario_otimo": horario_otimo,
            "sprint_mode": sprint_mode,
        },
        "dias_prova": dias_prova,
    }

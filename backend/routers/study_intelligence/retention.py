"""Curva de esquecimento: forgetting curve, alerts de retenção, resumo."""
from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Depends, Query

from database import get_db_session

router = APIRouter(prefix="", tags=["Study Intelligence"])

# ============================================================
# B2: FORGETTING CURVE VISUALIZER + PROACTIVE ALERTS
# ============================================================

# FSRS-5 retrievability formula: R(t, S) = (1 + t/(9*S))^(-1)
DESIRED_RETENTION = 0.9
REVIEW_TIME_FLASHCARD_MIN = 2
REVIEW_TIME_TOPICO_MIN = 5


def _calc_retrievability(elapsed_days: float, stability: float) -> float:
    """Calculate FSRS-5 retrievability: R = (1 + t/(9*S))^(-1)"""
    if stability <= 0:
        return 0.0
    return (1.0 + elapsed_days / (9.0 * stability)) ** (-1)


def _days_since_review(proxima_revisao: str, intervalo_dias: int, hoje: date) -> float:
    """Calculate days since last review based on proxima_revisao and interval.

    last_review = proxima_revisao - intervalo_dias
    days_since = hoje - last_review
    """
    if not proxima_revisao:
        return 0.0
    try:
        prox = date.fromisoformat(proxima_revisao)
        last_review = prox - timedelta(days=max(intervalo_dias or 1, 1))
        return max(0.0, (hoje - last_review).days)
    except (ValueError, TypeError):
        return 0.0


# ============================================================
# GET /api/study-intelligence/forgetting-curve
# ============================================================

@router.get("/api/study-intelligence/forgetting-curve",
            summary="Forgetting Curve Visualizer",
            description="""Gera curvas de esquecimento baseadas em FSRS-5 para visualização.
Retorna pontos de retenção projetados para os próximos 30 dias, agrupados por matéria.
Use para identificar quando a retenção cai abaixo do target (90%).""")
def forgetting_curve(
    materia: str | None = Query(None, description="Filtrar por matéria específica"),
    topico_id: int | None = Query(None, description="Filtrar por tópico do edital específico"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera curvas de esquecimento por matéria com projeção de 30 dias."""
    hoje = date.today()
    items = []  # List of dicts: {materia, stability, dias_desde_revisao, tipo}

    # --- 1. Query flashcards with stability > 0 ---
    fc_query = """
        SELECT id, materia, stability, proxima_revisao, intervalo_dias
        FROM flashcards
        WHERE user_id = ? AND stability > 0
    """
    fc_params = [user_id]

    if materia:
        fc_query += " AND materia = ?"
        fc_params.append(materia)

    flashcards = conn.execute(fc_query, fc_params).fetchall()
    for fc in flashcards:
        dias = _days_since_review(fc["proxima_revisao"], fc["intervalo_dias"], hoje)
        items.append({
            "materia": fc["materia"] or "Geral",
            "stability": fc["stability"],
            "dias_desde_revisao": dias,
            "tipo": "flashcard",
        })

    # --- 2. Query edital topics with stability_edital > 0 ---
    ed_query = """
        SELECT id, materia, topico, stability_edital, proxima_revisao, intervalo_revisao
        FROM edital
        WHERE user_id = ? AND stability_edital > 0 AND arquivado = 0
    """
    ed_params = [user_id]

    if topico_id:
        ed_query += " AND id = ?"
        ed_params.append(topico_id)
    elif materia:
        ed_query += " AND materia = ?"
        ed_params.append(materia)

    try:
        topicos = conn.execute(ed_query, ed_params).fetchall()
        for t in topicos:
            dias = _days_since_review(t["proxima_revisao"], t["intervalo_revisao"] if "intervalo_revisao" in t.keys() else 1, hoje)
            items.append({
                "materia": t["materia"] or "Geral",
                "stability": t["stability_edital"],
                "dias_desde_revisao": dias,
                "tipo": "topico",
            })
    except Exception:
        pass  # intervalo_revisao column might not exist in some setups

    if not items:
        return {
            "curvas": [],
            "desired_retention": DESIRED_RETENTION * 100,
            "total_items_analisados": 0,
            "mensagem": "Nenhum item com stability > 0 encontrado. Revise flashcards/tópicos para gerar curvas.",
        }

    # --- 3. Group by matéria ---
    materias_map: dict = {}
    for item in items:
        mat = item["materia"]
        if mat not in materias_map:
            materias_map[mat] = []
        materias_map[mat].append(item)

    # --- 4. Generate curves ---
    curvas = []

    # If materia was specified, return single aggregated curve
    # Otherwise, top 10 by item count
    if materia:
        materias_to_process = list(materias_map.keys())
    else:
        sorted_materias = sorted(materias_map.items(), key=lambda x: len(x[1]), reverse=True)
        materias_to_process = [m[0] for m in sorted_materias[:10]]

    for mat in materias_to_process:
        mat_items = materias_map[mat]
        stabilities = [i["stability"] for i in mat_items]
        stability_media = sum(stabilities) / len(stabilities)

        # Generate curve: for each day 0-30, calculate average retention
        pontos = []
        dia_critico = None

        for dia in range(31):
            retencoes = []
            for item in mat_items:
                # Total elapsed = dias_desde_revisao + dia (projection)
                elapsed = item["dias_desde_revisao"] + dia
                r = _calc_retrievability(elapsed, item["stability"])
                retencoes.append(r)

            avg_retencao = sum(retencoes) / len(retencoes)
            pontos.append({
                "dia": dia,
                "retencao": round(avg_retencao * 100, 1),
            })

            # Find critical day (first day below desired_retention)
            if dia_critico is None and avg_retencao < DESIRED_RETENTION:
                dia_critico = dia

        # Current retention (day 0)
        retencao_atual = pontos[0]["retencao"]

        curvas.append({
            "materia": mat,
            "stability_media": round(stability_media, 2),
            "retencao_atual": retencao_atual,
            "pontos": pontos,
            "dia_critico": dia_critico,
            "total_items": len(mat_items),
        })

    # Sort by lowest current retention (most at risk first)
    curvas.sort(key=lambda c: c["retencao_atual"])

    return {
        "curvas": curvas,
        "desired_retention": DESIRED_RETENTION * 100,
        "total_items_analisados": len(items),
    }


# ============================================================
# GET /api/study-intelligence/alerts
# ============================================================

@router.get("/api/study-intelligence/alerts",
            summary="Alertas proativos de esquecimento",
            description="""Identifica itens que cairão abaixo de 90% de retenção AMANHÃ.
Agrupa por matéria com urgência e tempo estimado de revisão.
Use para planejar sessões de revisão preventivas.""")
def forgetting_alerts(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna alertas proativos de itens em risco de esquecimento."""
    hoje = date.today()
    at_risk_items = []  # {materia, retencao_amanha, tipo}

    # --- 1. Flashcards com stability > 0 ---
    flashcards = conn.execute("""
        SELECT id, materia, stability, proxima_revisao, intervalo_dias
        FROM flashcards
        WHERE user_id = ? AND stability > 0
    """, (user_id,)).fetchall()

    for fc in flashcards:
        stability = fc["stability"]
        dias = _days_since_review(fc["proxima_revisao"], fc["intervalo_dias"], hoje)
        # Retention TOMORROW
        retencao_amanha = _calc_retrievability(dias + 1, stability)
        if retencao_amanha < DESIRED_RETENTION:
            at_risk_items.append({
                "materia": fc["materia"] or "Geral",
                "retencao_amanha": retencao_amanha,
                "tipo": "flashcard",
            })

    # --- 2. Edital topics com stability_edital > 0 ---
    try:
        topicos = conn.execute("""
            SELECT id, materia, stability_edital, proxima_revisao, intervalo_revisao
            FROM edital
            WHERE user_id = ? AND stability_edital > 0 AND arquivado = 0
        """, (user_id,)).fetchall()

        for t in topicos:
            stability = t["stability_edital"]
            intervalo = t["intervalo_revisao"] if "intervalo_revisao" in t.keys() else 1
            dias = _days_since_review(t["proxima_revisao"], intervalo, hoje)
            retencao_amanha = _calc_retrievability(dias + 1, stability)
            if retencao_amanha < DESIRED_RETENTION:
                at_risk_items.append({
                    "materia": t["materia"] or "Geral",
                    "retencao_amanha": retencao_amanha,
                    "tipo": "topico",
                })
    except Exception:
        pass

    if not at_risk_items:
        return {
            "alerts": [],
            "total_em_risco": 0,
            "tempo_total_min": 0,
            "mensagem": "✅ Nenhum item em risco de cair abaixo de 90% amanhã. Tudo sob controle!",
        }

    # --- 3. Group by matéria ---
    materias_map: dict = {}
    for item in at_risk_items:
        mat = item["materia"]
        if mat not in materias_map:
            materias_map[mat] = {"flashcards": 0, "topicos": 0, "retencoes": []}
        if item["tipo"] == "flashcard":
            materias_map[mat]["flashcards"] += 1
        else:
            materias_map[mat]["topicos"] += 1
        materias_map[mat]["retencoes"].append(item["retencao_amanha"])

    # --- 4. Build alerts ---
    alerts = []
    total_tempo = 0

    for mat, data in materias_map.items():
        n_flash = data["flashcards"]
        n_topico = data["topicos"]
        items_em_risco = n_flash + n_topico
        retencao_media = sum(data["retencoes"]) / len(data["retencoes"]) * 100
        tempo_revisao = n_flash * REVIEW_TIME_FLASHCARD_MIN + n_topico * REVIEW_TIME_TOPICO_MIN
        total_tempo += tempo_revisao

        # Urgência based on average retention
        if retencao_media < 70:
            urgencia = "alta"
        elif retencao_media < 80:
            urgencia = "media"
        else:
            urgencia = "baixa"

        alerts.append({
            "materia": mat,
            "items_em_risco": items_em_risco,
            "retencao_media": round(retencao_media, 1),
            "tempo_revisao_min": tempo_revisao,
            "urgencia": urgencia,
            "mensagem": f"{items_em_risco} itens de {mat} caem abaixo de 90% amanhã. ~{tempo_revisao}min de revisão.",
        })

    # Sort by urgency (alta first) then by items count
    urgencia_order = {"alta": 0, "media": 1, "baixa": 2}
    alerts.sort(key=lambda a: (urgencia_order.get(a["urgencia"], 3), -a["items_em_risco"]))

    return {
        "alerts": alerts,
        "total_em_risco": len(at_risk_items),
        "tempo_total_min": total_tempo,
    }


# ============================================================
# GET /api/study-intelligence/retention-summary
# ============================================================

@router.get("/api/study-intelligence/retention-summary",
            summary="Resumo de retenção geral",
            description="""Resumo geral de retenção: média hoje, projeções para 7 e 14 dias,
e contagem de itens abaixo do target agora vs. em 7 dias.""")
def retention_summary(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna resumo de retenção com projeções de 7 e 14 dias."""
    hoje = date.today()
    all_items = []  # {stability, dias_desde_revisao}

    # --- 1. Flashcards ---
    flashcards = conn.execute("""
        SELECT stability, proxima_revisao, intervalo_dias
        FROM flashcards
        WHERE user_id = ? AND stability > 0
    """, (user_id,)).fetchall()

    for fc in flashcards:
        dias = _days_since_review(fc["proxima_revisao"], fc["intervalo_dias"], hoje)
        all_items.append({
            "stability": fc["stability"],
            "dias_desde_revisao": dias,
        })

    # --- 2. Edital topics ---
    try:
        topicos = conn.execute("""
            SELECT stability_edital, proxima_revisao, intervalo_revisao
            FROM edital
            WHERE user_id = ? AND stability_edital > 0 AND arquivado = 0
        """, (user_id,)).fetchall()

        for t in topicos:
            intervalo = t["intervalo_revisao"] if "intervalo_revisao" in t.keys() else 1
            dias = _days_since_review(t["proxima_revisao"], intervalo, hoje)
            all_items.append({
                "stability": t["stability_edital"],
                "dias_desde_revisao": dias,
            })
    except Exception:
        pass

    if not all_items:
        return {
            "total_items": 0,
            "retencao_media_hoje": 0,
            "retencao_projecao_7d": 0,
            "retencao_projecao_14d": 0,
            "items_abaixo_target_hoje": 0,
            "items_abaixo_target_7d": 0,
            "desired_retention": DESIRED_RETENTION * 100,
            "mensagem": "Nenhum item com stability encontrado. Revise flashcards/tópicos para gerar dados.",
        }

    # --- 3. Calculate retention for today, +7d, +14d ---
    retencoes_hoje = []
    retencoes_7d = []
    retencoes_14d = []
    abaixo_hoje = 0
    abaixo_7d = 0

    for item in all_items:
        s = item["stability"]
        d = item["dias_desde_revisao"]

        r_hoje = _calc_retrievability(d, s)
        r_7d = _calc_retrievability(d + 7, s)
        r_14d = _calc_retrievability(d + 14, s)

        retencoes_hoje.append(r_hoje)
        retencoes_7d.append(r_7d)
        retencoes_14d.append(r_14d)

        if r_hoje < DESIRED_RETENTION:
            abaixo_hoje += 1
        if r_7d < DESIRED_RETENTION:
            abaixo_7d += 1

    avg_hoje = sum(retencoes_hoje) / len(retencoes_hoje) * 100
    avg_7d = sum(retencoes_7d) / len(retencoes_7d) * 100
    avg_14d = sum(retencoes_14d) / len(retencoes_14d) * 100

    # Trend analysis
    delta_7d = round(avg_7d - avg_hoje, 1)

    return {
        "total_items": len(all_items),
        "retencao_media_hoje": round(avg_hoje, 1),
        "retencao_projecao_7d": round(avg_7d, 1),
        "retencao_projecao_14d": round(avg_14d, 1),
        "items_abaixo_target_hoje": abaixo_hoje,
        "items_abaixo_target_7d": abaixo_7d,
        "desired_retention": DESIRED_RETENTION * 100,
        "tendencia_7d": delta_7d,
        "status": (
            "estável" if abs(delta_7d) <= 3
            else "em queda" if delta_7d < -3
            else "melhorando"
        ),
    }



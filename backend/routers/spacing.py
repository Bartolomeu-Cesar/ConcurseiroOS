"""Spacing Calculator — Gap ideal entre revisões por tópico.

Baseado em Cepeda et al. (2008): "Spacing effects in learning":
- Optimal spacing gap = 10-20% do período de retenção desejado
- Se quer lembrar por 30 dias, revise a cada 3-6 dias
- Adjustado pela stability individual (FSRS) de cada tópico

Fórmula:
  optimal_gap = stability * retention_factor
  retention_factor = -desired_retention / ln(desired_retention)
"""
import math
from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Depends, Query

from database import get_db_session

router = APIRouter(prefix="", tags=["Spacing Calculator"])

# Default desired retention (90%)
DEFAULT_RETENTION = 0.9


def _calculate_optimal_gap(stability: float, desired_retention: float = DEFAULT_RETENTION) -> float:
    """Calcula o gap ideal entre revisões (em dias).

    Args:
        stability: Stability do item (dias até retenção cair para desired_retention)
        desired_retention: Retenção desejada (0.8-0.95)

    Returns:
        Gap ideal em dias (float)
    """
    if stability <= 0:
        return 1.0

    # Fórmula baseada em Cepeda (2008):
    # Para manter retention R ao longo de T dias com spacing S:
    # optimal_gap ≈ stability * (-ln(desired_retention))
    # Mas limitado a 10-20% do período de retenção (stability)
    gap = stability * (-math.log(desired_retention))

    # Limites práticos
    gap = max(1.0, min(gap, stability * 0.3))  # Min 1 dia, max 30% da stability

    return round(gap, 1)


def _urgency_level(days_since_review: int, optimal_gap: float) -> str:
    """Classifica a urgência de revisão."""
    if days_since_review <= 0:
        return "ok"
    ratio = days_since_review / optimal_gap if optimal_gap > 0 else 999
    if ratio < 0.8:
        return "ok"         # Dentro do prazo
    elif ratio < 1.0:
        return "soon"       # Quase na hora
    elif ratio < 1.5:
        return "due"        # Na hora de revisar
    else:
        return "overdue"    # Atrasado


@router.get("/api/spacing", summary="Calculadora de spacing por tópico",
            description="Retorna o gap ideal entre revisões para cada tópico do edital, baseado na stability individual (FSRS).")
def get_spacing(
    materia: str = "",
    apenas_pendentes: bool = Query(False, description="Filtrar apenas tópicos com revisão pendente"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Calcula spacing ideal para cada tópico."""
    # Obter desired_retention do user
    config = conn.execute(
        "SELECT desired_retention FROM metas_config WHERE user_id = ?", (user_id,)
    ).fetchone()
    desired_retention = config["desired_retention"] if config and config["desired_retention"] else DEFAULT_RETENTION

    # Buscar tópicos do edital com dados de revisão
    try:
        query = """
            SELECT id, materia, topico, status, stability, ultima_revisao, proxima_revisao,
                   horas_estudadas
            FROM edital
            WHERE arquivado = 0 AND user_id = ?
        """
    except Exception:
        pass

    params = [user_id]

    if materia:
        query += " AND materia = ?"
        params.append(materia)

    query += " ORDER BY materia, topico"

    try:
        rows = conn.execute(query, params).fetchall()
    except Exception:
        # Fallback without stability column
        query_fb = """
            SELECT id, materia, topico, status, NULL as stability, ultima_revisao, proxima_revisao,
                   horas_estudadas
            FROM edital
            WHERE arquivado = 0 AND user_id = ?
        """
        params_fb = [user_id]
        if materia:
            query_fb += " AND materia = ?"
            params_fb.append(materia)
        query_fb += " ORDER BY materia, topico"
        rows = conn.execute(query_fb, params_fb).fetchall()

    hoje = date.today()
    topicos = []

    for r in rows:
        row = dict(r)
        stability = row.get("stability") or 0.0

        # Se não tem stability, usar heurística baseada em horas estudadas
        if stability <= 0:
            horas = row.get("horas_estudadas") or 0
            # Heurística: cada hora de estudo contribui ~2 dias de stability base
            stability = max(1.0, horas * 2.0)

        optimal_gap = _calculate_optimal_gap(stability, desired_retention)

        # Calcular dias desde última revisão
        ultima = row.get("ultima_revisao")
        if ultima:
            try:
                days_since = (hoje - date.fromisoformat(ultima)).days
            except (ValueError, TypeError):
                days_since = 999
        else:
            days_since = 999  # Nunca revisou

        # Calcular próxima revisão ideal
        if ultima:
            try:
                next_ideal = date.fromisoformat(ultima) + timedelta(days=int(optimal_gap))
            except (ValueError, TypeError):
                next_ideal = hoje
        else:
            next_ideal = hoje  # Deveria revisar agora

        urgency = _urgency_level(days_since, optimal_gap)

        # Filtro de pendentes
        if apenas_pendentes and urgency in ("ok", "soon"):
            continue

        topicos.append({
            "id": row["id"],
            "materia": row["materia"],
            "topico": row["topico"],
            "status": row["status"],
            "stability": round(stability, 1),
            "optimal_gap_dias": optimal_gap,
            "days_since_review": days_since,
            "proxima_revisao_ideal": next_ideal.isoformat(),
            "urgency": urgency,
        })

    # Ordenar por urgência (overdue primeiro)
    urgency_order = {"overdue": 0, "due": 1, "soon": 2, "ok": 3}
    topicos.sort(key=lambda t: (urgency_order.get(t["urgency"], 4), -t["days_since_review"]))

    # Stats resumo
    total = len(topicos)
    overdue = sum(1 for t in topicos if t["urgency"] == "overdue")
    due = sum(1 for t in topicos if t["urgency"] == "due")

    return {
        "desired_retention": desired_retention,
        "total_topicos": total,
        "overdue": overdue,
        "due": due,
        "topicos": topicos,
    }


@router.get("/api/spacing/resumo", summary="Resumo rápido de spacing",
            description="Retorna contagem de tópicos por urgência (para badges/alertas).")
def get_spacing_resumo(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Resumo rápido: quantos tópicos precisam de revisão."""
    config = conn.execute(
        "SELECT desired_retention FROM metas_config WHERE user_id = ?", (user_id,)
    ).fetchone()
    desired_retention = config["desired_retention"] if config and config["desired_retention"] else DEFAULT_RETENTION

    try:
        rows = conn.execute("""
            SELECT stability, ultima_revisao, horas_estudadas
            FROM edital
            WHERE arquivado = 0 AND status = 'Concluído' AND user_id = ?
        """, (user_id,)).fetchall()
    except Exception:
        # Fallback se stability/ultima_revisao columns não existem
        try:
            rows = conn.execute("""
                SELECT NULL as stability, NULL as ultima_revisao, horas_estudadas
                FROM edital
                WHERE arquivado = 0 AND status = 'Concluído' AND user_id = ?
            """, (user_id,)).fetchall()
        except Exception:
            return {"total_concluidos": 0, "ok": 0, "soon": 0, "due": 0, "overdue": 0, "precisam_revisao": 0}

    hoje = date.today()
    counts = {"ok": 0, "soon": 0, "due": 0, "overdue": 0}

    for r in rows:
        stability = r["stability"] or 0.0
        if stability <= 0:
            stability = max(1.0, (r["horas_estudadas"] or 0) * 2.0)

        optimal_gap = _calculate_optimal_gap(stability, desired_retention)

        ultima = r["ultima_revisao"]
        if ultima:
            try:
                days_since = (hoje - date.fromisoformat(ultima)).days
            except (ValueError, TypeError):
                days_since = 999
        else:
            days_since = 999

        urgency = _urgency_level(days_since, optimal_gap)
        counts[urgency] += 1

    return {
        "total_concluidos": sum(counts.values()),
        **counts,
        "precisam_revisao": counts["due"] + counts["overdue"],
    }

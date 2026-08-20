"""Router do Dashboard principal."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id
from models import DashboardResponse
from utils import today_str

router = APIRouter(prefix="", tags=["Dashboard"])


@router.get("/api/dashboard", response_model=DashboardResponse, summary="Dashboard principal",
            description="Retorna métricas consolidadas: horas, progresso, questões, flashcards")
def get_dashboard(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    # Horas por dia (últimos 14 dias)
    horas_dia = conn.execute("""
        SELECT data, SUM(horas) as total_horas
        FROM sessoes_estudo
        WHERE data >= ? AND user_id = ?
        GROUP BY data ORDER BY data
    """, ((date.today() - timedelta(days=13)).isoformat(), user_id)).fetchall()

    # Total de horas
    total_horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?", (user_id,)).fetchone()[0]

    # Horas por tipo de atividade
    horas_por_tipo = conn.execute("""
        SELECT tipo, COALESCE(SUM(horas), 0) as total
        FROM sessoes_estudo WHERE user_id = ? GROUP BY tipo
    """, (user_id,)).fetchall()
    horas_tipo_map = {r[0]: round(r[1], 1) for r in horas_por_tipo}
    horas_estudo = round(
        horas_tipo_map.get("edital", 0) + horas_tipo_map.get("ciclo", 0) + horas_tipo_map.get("timer", 0), 1
    )
    horas_questoes = round(horas_tipo_map.get("questoes", 0) + horas_tipo_map.get("simulado", 0), 1)

    # Progresso do edital
    edital_total = conn.execute("SELECT COUNT(*) FROM edital WHERE user_id = ?", (user_id,)).fetchone()[0]
    edital_concluido = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)).fetchone()[0]

    # Questões stats
    questoes_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    questoes_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]

    # Evolução de acertos por dia (últimos 14 dias)
    acertos_dia = conn.execute("""
        SELECT data, COUNT(*) as total, SUM(acertou) as acertos
        FROM questoes_respostas
        WHERE data >= ? AND user_id = ?
        GROUP BY data ORDER BY data
    """, ((date.today() - timedelta(days=13)).isoformat(), user_id)).fetchall()

    # Horas por matéria
    horas_materia = conn.execute("""
        SELECT materia, SUM(horas) as total
        FROM sessoes_estudo
        WHERE user_id = ?
        GROUP BY materia ORDER BY total DESC
    """, (user_id,)).fetchall()

    # Flashcards pendentes
    flashcards_pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)
    ).fetchone()[0]

    # Total flashcards
    flashcards_total = conn.execute("SELECT COUNT(*) FROM flashcards WHERE user_id = ?", (user_id,)).fetchone()[0]

    # Total flashcards revisados (histórico)
    flashcards_revisados_total = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    return {
        "horas_por_dia": [dict(r) for r in horas_dia],
        "total_horas": round(total_horas, 1),
        "horas_estudo": horas_estudo,
        "horas_questoes": horas_questoes,
        "edital": {"total": edital_total, "concluido": edital_concluido},
        "questoes": {
            "total": questoes_total,
            "acertos": questoes_acertos,
            "percentual": round((questoes_acertos / questoes_total * 100) if questoes_total > 0 else 0, 1)
        },
        "acertos_por_dia": [dict(r) for r in acertos_dia],
        "horas_por_materia": [dict(r) for r in horas_materia],
        "flashcards": {"pendentes": flashcards_pendentes, "total": flashcards_total, "revisados_total": flashcards_revisados_total}
    }

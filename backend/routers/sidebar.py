"""Endpoint consolidado para dados da sidebar — reduz 6 requests para 1."""
from deps import get_user_id
from fastapi import APIRouter, Depends
from services import get_horas_estudadas

from constants import (
    LEVEL_XP,
    XP_PER_CORRECT,
    XP_PER_FLASHCARD,
    XP_PER_HOUR,
    XP_PER_QUESTION,
    XP_PER_SIMULADO,
    XP_PER_TOPIC,
    XP_STREAK_WEEKLY_BONUS,
)
from database import get_db_session
from utils import calculate_streak, today_str

router = APIRouter()


@router.get("/api/sidebar-data", summary="Dados consolidados da sidebar",
            description="Retorna streak, gamificação, freezes, badges e sugestão rápida em um único request.")
def get_sidebar_data(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Consolida /api/streaks, /api/gamification, /api/streak-freeze,
    /api/flashcards/today (count), /api/sumulas/today (count),
    /api/questoes/erros/caderno (count) e /api/treinador/sugestao-rapida."""

    hoje = today_str()

    # --- Streak ---
    streak_info = calculate_streak(conn, user_id)

    # --- Gamificação (nível) ---
    horas = get_horas_estudadas(conn, user_id)
    questoes_total = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    questoes_certas = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)
    ).fetchone()[0]
    flashcards_rev = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    topicos_concluidos = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)
    ).fetchone()[0]
    simulados_feitos = conn.execute(
        "SELECT COUNT(*) FROM simulados WHERE status = 'finalizado' AND user_id = ?", (user_id,)
    ).fetchone()[0]

    streak = streak_info["streak_atual"]
    xp = int(
        horas * XP_PER_HOUR +
        questoes_total * XP_PER_QUESTION +
        questoes_certas * XP_PER_CORRECT +
        flashcards_rev * XP_PER_FLASHCARD +
        topicos_concluidos * XP_PER_TOPIC +
        simulados_feitos * XP_PER_SIMULADO +
        (streak // 7) * XP_STREAK_WEEKLY_BONUS
    )
    nivel = (xp // LEVEL_XP) + 1

    # --- Streak Freeze ---
    config = conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    freezes_available = 1
    if config and "streak_freezes_available" in config.keys():
        freezes_available = config["streak_freezes_available"]

    # --- Badges (contagens pendentes) ---
    flashcards_count = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()[0]

    sumulas_count = conn.execute(
        "SELECT COUNT(*) FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()[0]

    caderno_count = conn.execute(
        "SELECT COUNT(*) FROM erros_revisao WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()[0] if _table_exists(conn, "erros_revisao") else 0

    # --- Sugestão rápida ---
    sugestao = _get_sugestao_rapida(conn, user_id)

    return {
        "streak": streak_info["streak_atual"],
        "nivel": nivel,
        "xp": xp,
        "freezes_available": freezes_available,
        "badges": {
            "flashcards": flashcards_count,
            "sumulas": sumulas_count,
            "caderno": caderno_count,
        },
        "sugestao": sugestao,
    }


def _table_exists(conn, table_name: str) -> bool:
    """Verifica se uma tabela existe no banco."""
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def _get_sugestao_rapida(conn, user_id: int) -> dict:
    """Lógica simplificada de sugestão rápida para a sidebar."""
    # Matéria com menor acerto
    fraca = conn.execute("""
        SELECT q.materia, COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? GROUP BY q.materia HAVING total >= 3
        ORDER BY pct ASC LIMIT 1
    """, (user_id,)).fetchone()

    if fraca:
        return {"materia": fraca[0], "tempo_min": 25}

    # Fallback: matéria com menos horas estudadas
    row = conn.execute("""
        SELECT materia FROM edital WHERE status != 'Concluído' AND user_id = ?
        GROUP BY materia ORDER BY SUM(horas_estudadas) ASC LIMIT 1
    """, (user_id,)).fetchone()

    if row:
        return {"materia": row[0], "tempo_min": 25}

    return {}

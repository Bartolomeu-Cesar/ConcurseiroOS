"""Endpoint de Sugestão Rápida — GET /api/treinador/sugestao-rapida."""
from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id

router = APIRouter(prefix="", tags=["Treinador Inteligente"])


@router.get("/api/treinador/sugestao-rapida", summary="Sugestão rápida de matéria",
            description="Retorna a melhor matéria para estudar agora. Prioriza matéria com menor acerto e maior tempo sem estudar. Ideal para o CTA 'Iniciar Sessão'.")
def sugestao_rapida(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a melhor matéria para estudar agora (para CTA 'Iniciar Sessão')."""
    # Priority: matéria com menor acerto + mais tempo sem estudar
    fraca = conn.execute("""
        SELECT q.materia, COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? GROUP BY q.materia HAVING total >= 3
        ORDER BY pct ASC LIMIT 1
    """, (user_id,)).fetchone()

    if fraca:
        return {"materia": fraca[0], "motivo": f"Menor acerto ({fraca[2]}%)", "tempo_min": 25}

    # Fallback: matéria com menos horas estudadas (respeita cargo alvo)
    from services import edital_alvo_filter
    f_sql, f_params = edital_alvo_filter(conn, user_id)
    menos_estudada = conn.execute(f"""
        SELECT materia FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?{f_sql}
        GROUP BY materia ORDER BY SUM(horas_estudadas) ASC LIMIT 1
    """, (user_id, *f_params)).fetchone()

    if menos_estudada:
        return {"materia": menos_estudada[0], "motivo": "Menos estudada", "tempo_min": 25}

    # Final fallback
    return {"materia": "Revisão Geral", "motivo": "Estudo geral", "tempo_min": 25}

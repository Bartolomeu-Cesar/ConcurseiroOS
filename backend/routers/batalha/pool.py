"""Endpoint de polling global — GET /api/batalha/pendente."""
from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id

from .helpers import _ensure_battle_tables

router = APIRouter(prefix="/api/batalha", tags=["Batalha de Questões"])


@router.get("/pendente", summary="Batalha pendente (polling global)")
def batalha_pendente(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna info da batalha ativa do usuário (aguardando ou em_andamento). Usado para notificação global."""
    _ensure_battle_tables(conn)
    row = conn.execute("""
        SELECT b.codigo, b.titulo, b.status, b.total_rodadas, b.rodada_atual, b.criador_id
        FROM battles b
        JOIN battle_players bp ON bp.battle_id = b.id AND bp.user_id = ?
        WHERE b.status IN ('aguardando', 'em_andamento')
        ORDER BY b.created_at DESC LIMIT 1
    """, (user_id,)).fetchone()

    if not row:
        return {"ativa": False}

    return {
        "ativa": True,
        "codigo": row["codigo"],
        "titulo": row["titulo"],
        "status": row["status"],
        "total_rodadas": row["total_rodadas"],
        "rodada_atual": row["rodada_atual"],
        "is_creator": row["criador_id"] == user_id,
    }

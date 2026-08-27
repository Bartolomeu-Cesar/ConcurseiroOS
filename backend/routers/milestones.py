"""Progress Milestones — Celebrações em marcos de progresso.

Baseado na Goal-Setting Theory (Locke & Latham):
marcos em 25%, 50%, 75% e 100% geram motivação e senso de progresso.
"""
from datetime import datetime

from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id
from utils import today_str

router = APIRouter(prefix="", tags=["Progress Milestones"])

# Marcos de progresso (percentual)
MILESTONES = [25, 50, 75, 100]

# Mensagens motivacionais por marco
MILESTONE_MESSAGES = {
    25: {"emoji": "🌱", "titulo": "Primeiro quarto!", "msg": "Você completou 25% do edital. O início é o mais difícil — continue!"},
    50: {"emoji": "🔥", "titulo": "Metade concluída!", "msg": "Meio caminho andado! Seu esforço está dando resultado."},
    75: {"emoji": "🚀", "titulo": "Reta final!", "msg": "75% concluído! Faltam poucos tópicos. Você está quase lá!"},
    100: {"emoji": "🏆", "titulo": "Edital completo!", "msg": "Parabéns! Você concluiu 100% do edital. Hora de revisar e praticar!"},
}


@router.get("/api/milestones", summary="Verificar milestones do usuário",
            description="Retorna progresso atual do edital e milestones alcançados/pendentes.")
def get_milestones(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna milestones do edital principal."""
    # Progresso do edital (mesmo cálculo do dashboard)
    total = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE arquivado = 0 AND user_id = ?", (user_id,)
    ).fetchone()[0]

    concluido = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND arquivado = 0 AND user_id = ?", (user_id,)
    ).fetchone()[0]

    pct = round((concluido / total * 100) if total > 0 else 0, 1)

    # Milestones já atingidos (salvar para não celebrar repetidamente)
    _ensure_milestones_table(conn)
    achieved = conn.execute(
        "SELECT milestone_pct FROM milestones_achieved WHERE user_id = ?", (user_id,)
    ).fetchall()
    achieved_set = {r[0] for r in achieved}

    milestones = []
    new_milestones = []

    for m in MILESTONES:
        info = MILESTONE_MESSAGES[m].copy()
        info["pct"] = m
        info["achieved"] = m in achieved_set

        if pct >= m and m not in achieved_set:
            # Novo milestone atingido!
            info["new"] = True
            new_milestones.append(info)
            # Registrar
            conn.execute(
                "INSERT INTO milestones_achieved (user_id, milestone_pct, achieved_at) VALUES (?, ?, ?)",
                (user_id, m, datetime.now().isoformat())
            )
        else:
            info["new"] = False

        milestones.append(info)

    if new_milestones:
        conn.commit()

    return {
        "progresso_pct": pct,
        "total_topicos": total,
        "concluidos": concluido,
        "milestones": milestones,
        "new_milestones": new_milestones,
    }


@router.get("/api/milestones/check", summary="Check rápido de novos milestones",
            description="Retorna apenas novos milestones (para polling após completar tópico).")
def check_new_milestones(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Verifica se há milestones novos para celebrar (chamado após concluir tópico)."""
    total = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE arquivado = 0 AND user_id = ?", (user_id,)
    ).fetchone()[0]
    concluido = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND arquivado = 0 AND user_id = ?", (user_id,)
    ).fetchone()[0]

    if total == 0:
        return {"new_milestones": []}

    pct = round((concluido / total * 100), 1)

    _ensure_milestones_table(conn)
    achieved = conn.execute(
        "SELECT milestone_pct FROM milestones_achieved WHERE user_id = ?", (user_id,)
    ).fetchall()
    achieved_set = {r[0] for r in achieved}

    new_milestones = []
    for m in MILESTONES:
        if pct >= m and m not in achieved_set:
            info = MILESTONE_MESSAGES[m].copy()
            info["pct"] = m
            new_milestones.append(info)
            conn.execute(
                "INSERT INTO milestones_achieved (user_id, milestone_pct, achieved_at) VALUES (?, ?, ?)",
                (user_id, m, datetime.now().isoformat())
            )

    if new_milestones:
        conn.commit()

    return {"new_milestones": new_milestones}


def _ensure_milestones_table(conn):
    """Cria tabela de milestones se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS milestones_achieved (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            milestone_pct INTEGER NOT NULL,
            achieved_at TEXT NOT NULL,
            UNIQUE(user_id, milestone_pct)
        )
    """)

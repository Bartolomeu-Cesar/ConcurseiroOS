"""Router da Técnica Feynman."""
from datetime import datetime

from deps import get_user_id
from fastapi import APIRouter, Depends
from sanitize import sanitize_input
from schemas import FeynmanCreate

from database import get_db_session
from logger import log

router = APIRouter(prefix="", tags=["Feynman"])


@router.get("/api/feynman/{edital_id}")
def get_feynman(edital_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna explicações Feynman de um tópico"""
    rows = conn.execute("SELECT * FROM feynman WHERE edital_id = ? AND user_id = ? ORDER BY created_at DESC", (edital_id, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/feynman")
def create_feynman(body: FeynmanCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from utils import today_str, update_streak
    cur = conn.execute("INSERT INTO feynman (edital_id, explicacao, created_at, user_id) VALUES (?, ?, ?, ?)",
                       (body.edital_id, sanitize_input(body.explicacao, max_length=5000), datetime.now().isoformat(), user_id))

    # Registrar tempo (~5min por explicação Feynman) + streak
    horas_feynman = 5 / 60
    materia = conn.execute("SELECT materia FROM edital WHERE id = ? AND user_id = ?", (body.edital_id, user_id)).fetchone()
    mat_nome = materia["materia"] if materia else "Feynman"
    existing = conn.execute(
        "SELECT id FROM sessoes_estudo WHERE data = ? AND tipo = 'feynman' AND user_id = ?",
        (today_str(), user_id)
    ).fetchone()
    if existing:
        conn.execute("UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                     (horas_feynman, existing["id"], user_id))
    else:
        conn.execute(
            "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, 'feynman', ?, ?)",
            (mat_nome, horas_feynman, today_str(), user_id, datetime.now().isoformat())
        )
    update_streak(conn, "horas_estudadas", horas_feynman, user_id=user_id)

    conn.commit()
    log.info(f"Feynman explanation added for edital_id={body.edital_id}")
    return {"id": cur.lastrowid, "ok": True}

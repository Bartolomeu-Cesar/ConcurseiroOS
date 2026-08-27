"""Router da Técnica Feynman."""
from datetime import datetime

from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id
from logger import log
from sanitize import sanitize_input
from schemas import FeynmanCreate

router = APIRouter(prefix="", tags=["Feynman"])


@router.get("/api/feynman/{edital_id}")
def get_feynman(edital_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna explicações Feynman de um tópico"""
    rows = conn.execute("SELECT * FROM feynman WHERE edital_id = ? AND user_id = ? ORDER BY created_at DESC", (edital_id, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/feynman")
def create_feynman(body: FeynmanCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("INSERT INTO feynman (edital_id, explicacao, created_at, user_id) VALUES (?, ?, ?, ?)",
                       (body.edital_id, sanitize_input(body.explicacao, max_length=5000), datetime.now().isoformat(), user_id))
    conn.commit()
    log.info(f"Feynman explanation added for edital_id={body.edital_id}")
    return {"id": cur.lastrowid, "ok": True}

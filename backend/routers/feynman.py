"""Router da Técnica Feynman."""
from datetime import datetime

from fastapi import APIRouter, Depends

from database import get_db_session
from logger import log
from models import FeynmanCreate

router = APIRouter(prefix="", tags=["Feynman"])


@router.get("/api/feynman/{edital_id}")
def get_feynman(edital_id: int, conn=Depends(get_db_session)):
    """Retorna explicações Feynman de um tópico"""
    rows = conn.execute("SELECT * FROM feynman WHERE edital_id = ? ORDER BY created_at DESC", (edital_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/feynman")
def create_feynman(body: FeynmanCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO feynman (edital_id, explicacao, created_at) VALUES (?, ?, ?)",
                       (body.edital_id, body.explicacao, datetime.now().isoformat()))
    conn.commit()
    log.info(f"Feynman explanation added for edital_id={body.edital_id}")
    return {"id": cur.lastrowid, "ok": True}

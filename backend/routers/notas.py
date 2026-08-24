"""Router de Notas de PDF."""
from datetime import datetime

from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import NotaCreate, OkResponse

router = APIRouter(prefix="", tags=["Notas"])


@router.get("/api/notas/{path:path}")
def get_notas_pdf(path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM notas_pdf WHERE pdf_path = ? AND user_id = ? ORDER BY pagina, id", (path, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/notas")
def create_nota(body: NotaCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
                       (body.pdf_path, body.pagina, body.conteudo, datetime.now().isoformat(), user_id))
    conn.commit()
    log.info(f"Nota created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas/{id}", response_model=OkResponse)
def delete_nota(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM notas_pdf WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}

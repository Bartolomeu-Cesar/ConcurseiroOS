"""Router de Notas de PDF."""
from datetime import datetime

from fastapi import APIRouter, Depends

from database import get_db_session
from logger import log
from models import NotaCreate, OkResponse

router = APIRouter(prefix="", tags=["Notas"])


@router.get("/api/notas/{path:path}")
def get_notas_pdf(path: str, conn=Depends(get_db_session)):
    rows = conn.execute("SELECT * FROM notas_pdf WHERE pdf_path = ? ORDER BY pagina, id", (path,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/notas")
def create_nota(body: NotaCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at) VALUES (?, ?, ?, ?)",
                       (body.pdf_path, body.pagina, body.conteudo, datetime.now().isoformat()))
    conn.commit()
    log.info(f"Nota created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas/{id}", response_model=OkResponse)
def delete_nota(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM notas_pdf WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}

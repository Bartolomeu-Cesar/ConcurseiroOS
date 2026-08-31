"""Router de Notas de PDF."""
from datetime import datetime

from deps import get_user_id
from fastapi import APIRouter, Depends, Query
from sanitize import sanitize_input
from schemas import NotaCreate, OkResponse

from database import get_db_session
from logger import log

router = APIRouter(prefix="", tags=["Notas"])


@router.get("/api/notas", summary="Listar notas de um PDF (query string)",
            description="Lista notas por pdf_path (query), com filtro opcional de página.")
def list_notas_query(
    pdf_path: str = Query(..., description="Caminho do PDF"),
    pagina: int | None = Query(None, description="Filtrar por página (opcional)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Endpoint consumido pelo viewer (query string + filtro por página).

    Mantém compatibilidade com o endpoint path-param GET /api/notas/{path}.
    """
    if pagina is not None:
        rows = conn.execute(
            "SELECT * FROM notas_pdf WHERE pdf_path = ? AND pagina = ? AND user_id = ? ORDER BY id",
            (pdf_path, pagina, user_id),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM notas_pdf WHERE pdf_path = ? AND user_id = ? ORDER BY pagina, id",
            (pdf_path, user_id),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/notas/{path:path}")
def get_notas_pdf(path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM notas_pdf WHERE pdf_path = ? AND user_id = ? ORDER BY pagina, id", (path, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/notas")
def create_nota(body: NotaCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conteudo = sanitize_input(body.conteudo, max_length=2000)
    cur = conn.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
                       (body.pdf_path, body.pagina, conteudo, datetime.now().isoformat(), user_id))
    conn.commit()
    log.info(f"Nota created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas/{id}", response_model=OkResponse)
def delete_nota(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM notas_pdf WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}

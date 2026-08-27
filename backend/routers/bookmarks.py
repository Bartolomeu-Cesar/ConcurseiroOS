"""Router de Bookmarks de PDF."""
from datetime import datetime

from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id
from logger import log
from sanitize import sanitize_input
from schemas import BookmarkCreate, OkResponse

router = APIRouter(prefix="", tags=["Bookmarks"])


@router.get("/api/bookmarks/{path:path}")
def get_bookmarks(path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM bookmarks_pdf WHERE pdf_path = ? AND user_id = ? ORDER BY pagina", (path, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/bookmarks")
def create_bookmark(body: BookmarkCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    label = sanitize_input(body.label) if body.label else ""
    cur = conn.execute("INSERT INTO bookmarks_pdf (pdf_path, pagina, label, cor, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                       (body.pdf_path, body.pagina, label, body.cor, datetime.now().isoformat(), user_id))
    conn.commit()
    log.info(f"Bookmark created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/bookmarks/{id}", response_model=OkResponse)
def delete_bookmark(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM bookmarks_pdf WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}

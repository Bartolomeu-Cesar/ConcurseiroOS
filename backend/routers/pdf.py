import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from database import get_db_session
from deps import get_user_id
from models import ProgressUpdate
from utils import build_tree, get_pdf_pages

router = APIRouter(prefix="", tags=["PDFs"])

PDF_ROOT = None  # Set from main.py


def set_pdf_root(root: str):
    global PDF_ROOT
    PDF_ROOT = root


@router.get("/api/tree", summary="Árvore de PDFs", description="Retorna a estrutura de diretórios e arquivos PDF disponíveis")
def get_tree():
    if not Path(PDF_ROOT).exists():
        return []
    return build_tree(PDF_ROOT)


@router.get("/api/progress/{path:path}")
def get_progress(path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    # Validate path doesn't contain traversal sequences
    if ".." in path:
        raise HTTPException(status_code=400, detail="Caminho inválido")
    row = conn.execute(
        "SELECT current_page, total_pages FROM progress WHERE path = ? AND user_id = ?",
        (path, user_id)
    ).fetchone()
    if row:
        return {"current_page": row[0], "total_pages": row[1]}
    total = get_pdf_pages(str(Path(PDF_ROOT) / path))
    return {"current_page": 1, "total_pages": total}


@router.post("/api/progress/{path:path}")
def save_progress(path: str, body: ProgressUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    # Validate path doesn't contain traversal sequences
    if ".." in path:
        raise HTTPException(status_code=400, detail="Caminho inválido")
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    # Ensure last_read_at column exists
    try:
        conn.execute("SELECT last_read_at FROM progress LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE progress ADD COLUMN last_read_at TEXT DEFAULT ''")
    conn.execute("""
        INSERT INTO progress (path, current_page, total_pages, user_id, last_read_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET current_page=excluded.current_page, total_pages=excluded.total_pages, last_read_at=excluded.last_read_at
    """, (path, body.current_page, body.total_pages, user_id, now))
    conn.commit()
    return {"ok": True}


@router.get("/api/progress/recentes", summary="PDFs lidos recentemente")
def get_recentes(limit: int = 5, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna os últimos PDFs lidos com progresso de leitura."""
    # Ensure last_read_at column exists
    try:
        conn.execute("SELECT last_read_at FROM progress LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE progress ADD COLUMN last_read_at TEXT DEFAULT ''")
        conn.commit()
    rows = conn.execute("""
        SELECT path, current_page, total_pages, last_read_at
        FROM progress WHERE user_id = ? AND last_read_at != ''
        ORDER BY last_read_at DESC LIMIT ?
    """, (user_id, limit)).fetchall()
    return [{
        "path": r[0],
        "nome": r[0].split("/")[-1].replace(".pdf", "").replace("-completo", ""),
        "current_page": r[1],
        "total_pages": r[2],
        "progresso_pct": round(r[1] / r[2] * 100) if r[2] > 0 else 0,
        "last_read_at": r[3],
    } for r in rows]


@router.get("/api/progress-bulk")
def get_progress_bulk(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        "SELECT path, current_page, total_pages FROM progress WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    return {r[0]: {"current_page": r[1], "total_pages": r[2]} for r in rows}


@router.get("/pdf/{path:path}")
def serve_pdf(path: str):
    # Path traversal protection: reject obvious traversal attempts
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=403, detail="Acesso negado")
    full = Path(PDF_ROOT) / path
    # Verify the logical path stays within PDF_ROOT (without resolving symlinks)
    try:
        full.relative_to(Path(PDF_ROOT))
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado")
    # Resolve for actual file access
    resolved = full.resolve()
    if not resolved.exists() or resolved.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF não encontrado")
    return FileResponse(str(resolved), media_type="application/pdf")


@router.get("/api/export")
def export_progress(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        "SELECT path, current_page, total_pages FROM progress WHERE user_id = ?",
        (user_id,)
    ).fetchall()
    data = [{"path": r[0], "current_page": r[1], "total_pages": r[2]} for r in rows]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="leitor_progress.json", background=None)


@router.post("/api/import")
async def import_progress(file: UploadFile = File(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    content = await file.read()
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Arquivo JSON inválido") from None
    for item in data:
        conn.execute("""
            INSERT INTO progress (path, current_page, total_pages, user_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                current_page = MAX(current_page, excluded.current_page),
                total_pages  = excluded.total_pages
        """, (item["path"], item["current_page"], item["total_pages"], user_id))
    conn.commit()
    return {"ok": True, "imported": len(data)}

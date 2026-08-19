import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from database import get_db
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
def get_progress(path: str):
    with get_db() as conn:
        row = conn.execute("SELECT current_page, total_pages FROM progress WHERE path = ?", (path,)).fetchone()
        if row:
            return {"current_page": row[0], "total_pages": row[1]}
    total = get_pdf_pages(str(Path(PDF_ROOT) / path))
    return {"current_page": 1, "total_pages": total}


@router.post("/api/progress/{path:path}")
def save_progress(path: str, body: ProgressUpdate):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO progress (path, current_page, total_pages)
            VALUES (?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET current_page=excluded.current_page, total_pages=excluded.total_pages
        """, (path, body.current_page, body.total_pages))
        conn.commit()
    return {"ok": True}


@router.get("/api/progress-bulk")
def get_progress_bulk():
    with get_db() as conn:
        rows = conn.execute("SELECT path, current_page, total_pages FROM progress").fetchall()
    return {r[0]: {"current_page": r[1], "total_pages": r[2]} for r in rows}


@router.get("/pdf/{path:path}")
def serve_pdf(path: str):
    full = Path(PDF_ROOT) / path
    if not full.exists() or full.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF não encontrado")
    return FileResponse(str(full), media_type="application/pdf")


@router.get("/api/export")
def export_progress():
    with get_db() as conn:
        rows = conn.execute("SELECT path, current_page, total_pages FROM progress").fetchall()
    data = [{"path": r[0], "current_page": r[1], "total_pages": r[2]} for r in rows]
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="leitor_progress.json", background=None)


@router.post("/api/import")
async def import_progress(file: UploadFile = File(...)):
    content = await file.read()
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(status_code=400, detail="Arquivo JSON inválido") from None
    with get_db() as conn:
        for item in data:
            conn.execute("""
                INSERT INTO progress (path, current_page, total_pages)
                VALUES (?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    current_page = MAX(current_page, excluded.current_page),
                    total_pages  = excluded.total_pages
            """, (item["path"], item["current_page"], item["total_pages"]))
        conn.commit()
    return {"ok": True, "imported": len(data)}

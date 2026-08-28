import json
import tempfile
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from database import get_db_session
from deps import get_user_id
from schemas import ProgressUpdate
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


@router.post("/api/pdfs/upload", summary="Upload de PDF para estudo",
             description="Faz upload de um arquivo PDF para a biblioteca de estudo.")
async def upload_pdf(file: UploadFile = File(...), user_id: int = Depends(get_user_id), conn=Depends(get_db_session)):
    """Salva um PDF na pasta de PDFs para leitura no viewer."""
    from plans import enforce_plan_limit
    enforce_plan_limit(conn, user_id, "pdfs")

    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    # Sanitize filename
    import re
    safe_name = re.sub(r'[^\w\s\-.]', '', file.filename).strip()
    if not safe_name:
        safe_name = "documento.pdf"
    if not safe_name.lower().endswith('.pdf'):
        safe_name += '.pdf'

    # Ensure pdfs directory exists
    pdf_dir = Path(PDF_ROOT)
    pdf_dir.mkdir(parents=True, exist_ok=True)

    # Avoid overwriting existing files
    target = pdf_dir / safe_name
    if target.exists():
        base = safe_name[:-4]
        i = 1
        while target.exists():
            target = pdf_dir / f"{base}_{i}.pdf"
            i += 1
        safe_name = target.name

    # Save file
    content = await file.read()
    target.write_bytes(content)

    # Get page count
    total_pages = get_pdf_pages(str(target))

    return {
        "ok": True,
        "filename": safe_name,
        "path": safe_name,
        "total_pages": total_pages,
        "size_mb": round(len(content) / (1024 * 1024), 2),
    }


@router.delete("/api/pdfs/{path:path}", summary="Excluir PDF")
def delete_pdf(path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Remove um PDF da biblioteca."""
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=403, detail="Acesso negado")
    target = Path(PDF_ROOT) / path
    try:
        target.relative_to(Path(PDF_ROOT))
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado")
    if not target.exists():
        raise HTTPException(status_code=404, detail="PDF não encontrado")
    target.unlink()
    # Remove progress record
    conn.execute("DELETE FROM progress WHERE path = ? AND user_id = ?", (path, user_id))
    conn.commit()
    return {"ok": True, "deleted": path}


# ==================== ORGANIZAÇÃO VIRTUAL DE PDFS ====================
# Pastas virtuais por usuário (não move arquivos reais)

@router.get("/api/pdf/organizacao", summary="Árvore organizada pelo usuário",
            description="Retorna a árvore de PDFs reorganizada pelo usuário com pastas virtuais.")
def get_organizacao(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna árvore real + overlay de organização virtual do usuário."""
    from utils import build_tree

    # Árvore real do filesystem
    tree_real = build_tree(PDF_ROOT) if Path(PDF_ROOT).exists() else []

    # Buscar pastas virtuais do usuário
    pastas = conn.execute(
        "SELECT id, nome, parent_id, posicao FROM pdf_pastas_virtuais WHERE user_id = ? ORDER BY posicao",
        (user_id,)
    ).fetchall()

    # Buscar mapeamento de PDFs para pastas virtuais
    org = conn.execute(
        "SELECT pdf_path, pasta_virtual_id, posicao FROM pdf_organizacao WHERE user_id = ? ORDER BY posicao",
        (user_id,)
    ).fetchall()

    if not pastas and not org:
        # Sem organização personalizada — retorna árvore real
        return {"organizado": False, "tree": tree_real}

    # Montar árvore virtual
    pastas_map = {p["id"]: {"id": p["id"], "type": "folder", "name": p["nome"], "virtual": True, "children": [], "parent_id": p["parent_id"]} for p in pastas}
    org_map = {o["pdf_path"]: o["pasta_virtual_id"] for o in org}

    # Coletar todos os PDFs da árvore real (flatten)
    all_pdfs = {}
    def _flatten(nodes, prefix=""):
        for n in nodes:
            if n["type"] == "pdf":
                path = prefix + "/" + n["name"] if prefix else n["name"]
                if "path" in n:
                    path = n["path"]
                all_pdfs[path] = n
            elif n["type"] == "folder":
                _flatten(n.get("children", []), prefix + "/" + n["name"] if prefix else n["name"])
    _flatten(tree_real)

    # Distribuir PDFs nas pastas virtuais
    pdfs_organizados = set()
    for pdf_path, pasta_id in org_map.items():
        if pdf_path in all_pdfs and pasta_id in pastas_map:
            pastas_map[pasta_id]["children"].append(all_pdfs[pdf_path])
            pdfs_organizados.add(pdf_path)

    # Montar hierarquia de pastas (parent_id → children)
    root_folders = []
    for pasta in pastas_map.values():
        parent_id = pasta.pop("parent_id", None)
        if parent_id and parent_id in pastas_map:
            pastas_map[parent_id]["children"].append(pasta)
        else:
            root_folders.append(pasta)

    # PDFs não organizados ficam na raiz
    nao_organizados = []
    for path, pdf in all_pdfs.items():
        if path not in pdfs_organizados:
            nao_organizados.append(pdf)

    # Resultado: pastas virtuais primeiro, depois não-organizados
    tree_final = root_folders + nao_organizados

    return {"organizado": True, "tree": tree_final, "total_pdfs": len(all_pdfs), "organizados": len(pdfs_organizados)}


@router.post("/api/pdf/pastas", summary="Criar pasta virtual")
def criar_pasta_virtual(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Cria uma nova pasta virtual para organizar PDFs."""
    from utils import today_str
    nome = body.get("nome", "").strip()
    parent_id = body.get("parent_id")

    if not nome:
        raise HTTPException(status_code=400, detail="Nome da pasta é obrigatório")

    cur = conn.execute(
        "INSERT INTO pdf_pastas_virtuais (user_id, nome, parent_id, posicao, created_at) VALUES (?, ?, ?, 0, ?)",
        (user_id, nome, parent_id, today_str())
    )
    conn.commit()
    return {"ok": True, "id": cur.lastrowid, "nome": nome}


@router.put("/api/pdf/pastas/{pasta_id}", summary="Renomear pasta virtual")
def renomear_pasta(
    pasta_id: int,
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Renomeia uma pasta virtual."""
    nome = body.get("nome", "").strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Nome é obrigatório")
    conn.execute(
        "UPDATE pdf_pastas_virtuais SET nome = ? WHERE id = ? AND user_id = ?",
        (nome, pasta_id, user_id)
    )
    conn.commit()
    return {"ok": True}


@router.delete("/api/pdf/pastas/{pasta_id}", summary="Excluir pasta virtual")
def excluir_pasta(pasta_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Exclui pasta virtual (PDFs voltam para raiz, não são deletados)."""
    conn.execute("DELETE FROM pdf_organizacao WHERE pasta_virtual_id = ? AND user_id = ?", (pasta_id, user_id))
    conn.execute("DELETE FROM pdf_pastas_virtuais WHERE id = ? AND user_id = ?", (pasta_id, user_id))
    conn.commit()
    return {"ok": True}


@router.post("/api/pdf/mover", summary="Mover PDF para pasta virtual",
             description="Move um PDF para dentro de uma pasta virtual (ou para raiz se pasta_id=null)")
def mover_pdf(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Move um PDF para uma pasta virtual.

    body: {pdf_path: str, pasta_virtual_id: int|null, posicao: int (opcional)}
    Se pasta_virtual_id=null, remove da organização (volta para posição real).
    """
    pdf_path = body.get("pdf_path", "").strip()
    pasta_id = body.get("pasta_virtual_id")
    posicao = body.get("posicao", 0)

    if not pdf_path:
        raise HTTPException(status_code=400, detail="pdf_path é obrigatório")

    if pasta_id is None:
        # Remover da organização (voltar para raiz)
        conn.execute("DELETE FROM pdf_organizacao WHERE pdf_path = ? AND user_id = ?", (pdf_path, user_id))
    else:
        # Inserir ou atualizar organização
        existing = conn.execute(
            "SELECT id FROM pdf_organizacao WHERE pdf_path = ? AND user_id = ?", (pdf_path, user_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE pdf_organizacao SET pasta_virtual_id = ?, posicao = ? WHERE pdf_path = ? AND user_id = ?",
                (pasta_id, posicao, pdf_path, user_id)
            )
        else:
            conn.execute(
                "INSERT INTO pdf_organizacao (user_id, pdf_path, pasta_virtual_id, posicao) VALUES (?, ?, ?, ?)",
                (user_id, pdf_path, pasta_id, posicao)
            )
    conn.commit()
    return {"ok": True, "pdf_path": pdf_path, "pasta_virtual_id": pasta_id}

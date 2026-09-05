import json
import tempfile
from pathlib import Path

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from schemas import ProgressUpdate

from database import get_db_session
from utils import build_tree, get_pdf_pages

router = APIRouter(prefix="", tags=["PDFs"])

PDF_ROOT = None  # Set from main.py


def set_pdf_root(root: str):
    global PDF_ROOT
    PDF_ROOT = root


# ==================== AUTORIZAÇÃO DE VISIBILIDADE ====================
# Arquivos são globais no disco, mas a visibilidade é controlada por metadados:
# um usuário só acessa um PDF se for o dono OU se o dono compartilhou com ele.

def get_owner_id(conn, path: str):
    """Retorna o owner_id de um PDF, ou None se não houver dono registrado."""
    row = conn.execute(
        "SELECT owner_id FROM pdf_owner WHERE pdf_path = ?", (path,)
    ).fetchone()
    return row[0] if row else None


def _is_admin(conn, user_id: int) -> bool:
    """True se o usuário tem role='admin'."""
    try:
        row = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
    except Exception:
        return False
    if not row:
        return False
    # Suporta row_factory=Row e tupla
    try:
        return row["role"] == "admin"
    except (TypeError, IndexError, KeyError):
        return len(row) > 0 and row[0] == "admin"


def can_access(conn, user_id: int, path: str) -> bool:
    """True se o usuário pode ver o PDF: é o dono OU o dono compartilhou com ele.

    Política fail-closed: PDF sem dono registrado é INVISÍVEL (acesso negado) —
    EXCETO para administradores, que veem PDFs órfãos para poder compartilhá-los
    ou definir o dono.
    Todo PDF acessível precisa ter um dono em pdf_owner — uploads registram o
    dono e a migration de backfill atribuiu os arquivos existentes ao uid 1.
    """
    owner_id = get_owner_id(conn, path)
    if owner_id is None:
        return _is_admin(conn, user_id)  # órfão: só admin vê (fail-closed p/ os demais)
    if owner_id == user_id:
        return True
    shared = conn.execute(
        "SELECT 1 FROM pdf_compartilhamentos WHERE pdf_path = ? AND shared_with_id = ?",
        (path, user_id)
    ).fetchone()
    return shared is not None


def _orphan_paths(conn) -> set:
    """PDFs presentes no disco que NÃO têm dono registrado (órfãos)."""
    if not PDF_ROOT or not Path(PDF_ROOT).exists():
        return set()
    owned = {r[0] for r in conn.execute("SELECT pdf_path FROM pdf_owner").fetchall()}
    disco = set()

    def _collect(nodes):
        for n in nodes:
            if n.get("type") == "pdf" and n.get("path"):
                disco.add(n["path"])
            elif n.get("type") == "folder":
                _collect(n.get("children", []))
    _collect(build_tree(PDF_ROOT))
    return disco - owned


def visible_paths(conn, user_id: int) -> set:
    """Conjunto de pdf_paths que o usuário pode ver (dono + compartilhados).

    Administradores também veem os PDFs órfãos (sem dono registrado).
    """
    paths = set()
    for r in conn.execute(
        "SELECT pdf_path FROM pdf_owner WHERE owner_id = ?", (user_id,)
    ).fetchall():
        paths.add(r[0])
    for r in conn.execute(
        "SELECT pdf_path FROM pdf_compartilhamentos WHERE shared_with_id = ?", (user_id,)
    ).fetchall():
        paths.add(r[0])
    if _is_admin(conn, user_id):
        paths |= _orphan_paths(conn)
    return paths


def _filter_tree(nodes, allowed: set):
    """Filtra a árvore de PDFs mantendo apenas os visíveis ao usuário.

    Política fail-closed: um PDF só aparece se estiver em `allowed` (dono ou
    compartilhado). PDFs sem dono registrado ficam ocultos. Pastas vazias após
    o filtro são removidas.
    """
    result = []
    for n in nodes:
        if n.get("type") == "pdf":
            if n.get("path") in allowed:
                result.append(n)
        elif n.get("type") == "folder":
            children = _filter_tree(n.get("children", []), allowed)
            if children:
                result.append({**n, "children": children})
    return result


@router.get("/api/tree", summary="Árvore de PDFs", description="Retorna a estrutura de diretórios e arquivos PDF disponíveis")
def get_tree(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if not Path(PDF_ROOT).exists():
        return []
    tree = build_tree(PDF_ROOT)
    allowed = visible_paths(conn, user_id)
    return _filter_tree(tree, allowed)


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
        ON CONFLICT(path, user_id) DO UPDATE SET current_page=excluded.current_page, total_pages=excluded.total_pages, last_read_at=excluded.last_read_at
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


@router.get("/api/pdf-existe/{path:path}", summary="Verificar se um PDF existe",
            description="Checagem leve de existência de um PDF (sem transferir o arquivo).")
def pdf_existe(path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna {existe: bool} para o caminho de PDF informado.

    Usado pelo viewer para avisar o usuário quando o arquivo não existe mais
    no diretório, em vez de exibir o erro genérico do PDF.js. Respeita a
    visibilidade: se o usuário não tem acesso, retorna existe=False.
    """
    if ".." in path or path.startswith("/"):
        return {"existe": False}
    if not can_access(conn, user_id, path):
        return {"existe": False}
    full = Path(PDF_ROOT) / path
    try:
        full.relative_to(Path(PDF_ROOT))
    except ValueError:
        return {"existe": False}
    resolved = full.resolve()
    existe = resolved.exists() and resolved.suffix.lower() == ".pdf"
    return {"existe": existe}


@router.get("/pdf/{path:path}")
def serve_pdf(path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    # Path traversal protection: reject obvious traversal attempts
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=403, detail="Acesso negado")
    # Autorização de visibilidade: dono ou compartilhado
    if not can_access(conn, user_id, path):
        raise HTTPException(status_code=403, detail="Acesso negado")
    full = Path(PDF_ROOT) / path
    # Verify the logical path stays within PDF_ROOT (without resolving symlinks)
    try:
        full.relative_to(Path(PDF_ROOT))
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado") from None
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
            ON CONFLICT(path, user_id) DO UPDATE SET
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

    # Registrar o dono do PDF (visibilidade por usuário)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, ?, ?)",
        (safe_name, user_id, now)
    )
    conn.commit()

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
    """Remove um PDF da biblioteca.

    - Se o usuário for o dono: apaga o arquivo físico e todos os metadados
      (progresso, compartilhamentos, registro de dono).
    - Se o usuário NÃO for o dono (é um PDF compartilhado com ele): apenas
      remove o acesso dele (descompartilha) e seu próprio progresso — o arquivo
      e o acesso dos demais permanecem intactos.
    """
    if ".." in path or path.startswith("/"):
        raise HTTPException(status_code=403, detail="Acesso negado")

    # Sem permissão nenhuma de ver o arquivo
    if not can_access(conn, user_id, path):
        raise HTTPException(status_code=403, detail="Acesso negado")

    owner_id = get_owner_id(conn, path)

    # Não-dono: apenas remove o próprio acesso e progresso (não apaga arquivo)
    if owner_id is not None and owner_id != user_id:
        conn.execute(
            "DELETE FROM pdf_compartilhamentos WHERE pdf_path = ? AND shared_with_id = ?",
            (path, user_id)
        )
        conn.execute("DELETE FROM progress WHERE path = ? AND user_id = ?", (path, user_id))
        conn.commit()
        return {"ok": True, "removido_da_biblioteca": path, "arquivo_apagado": False}

    # Dono (ou PDF legado sem dono): apaga arquivo físico e metadados
    target = Path(PDF_ROOT) / path
    try:
        target.relative_to(Path(PDF_ROOT))
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado") from None
    if target.exists():
        target.unlink()
    conn.execute("DELETE FROM progress WHERE path = ?", (path,))
    conn.execute("DELETE FROM pdf_compartilhamentos WHERE pdf_path = ?", (path,))
    conn.execute("DELETE FROM pdf_owner WHERE pdf_path = ?", (path,))
    conn.commit()
    return {"ok": True, "deleted": path, "arquivo_apagado": True}


# ==================== ORGANIZAÇÃO VIRTUAL DE PDFS ====================
# Pastas virtuais por usuário (não move arquivos reais)

@router.get("/api/pdf/organizacao", summary="Árvore organizada pelo usuário",
            description="Retorna a árvore de PDFs reorganizada pelo usuário com pastas virtuais.")
def get_organizacao(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna árvore real + overlay de organização virtual do usuário."""
    from utils import build_tree

    # Árvore real do filesystem (filtrada por visibilidade)
    tree_real = build_tree(PDF_ROOT) if Path(PDF_ROOT).exists() else []
    allowed = visible_paths(conn, user_id)
    tree_real = _filter_tree(tree_real, allowed)

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


# ==================== COMPARTILHAMENTO SELF-SERVICE ====================
# O próprio dono compartilha seus PDFs com outros usuários (por email/username).

def _resolve_user(conn, ident):
    """Resolve um usuário por id (int), email ou username. Retorna row (id, nome, email, username) ou None."""
    if ident is None:
        return None
    ident_str = str(ident).strip()
    if not ident_str:
        return None
    # Numérico → id
    if ident_str.isdigit():
        return conn.execute(
            "SELECT id, nome, email, username FROM users WHERE id = ?", (int(ident_str),)
        ).fetchone()
    # Email ou username (case-insensitive)
    return conn.execute(
        "SELECT id, nome, email, username FROM users WHERE LOWER(email) = LOWER(?) OR LOWER(username) = LOWER(?)",
        (ident_str, ident_str)
    ).fetchone()


@router.get("/api/pdf/meus", summary="Meus PDFs e compartilhamentos",
            description="Lista os PDFs de que o usuário é dono e com quem cada um está compartilhado.")
def meus_pdfs(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna os PDFs do dono + os compartilhados comigo."""
    # PDFs de que sou dono
    donos = conn.execute(
        "SELECT pdf_path FROM pdf_owner WHERE owner_id = ? ORDER BY pdf_path", (user_id,)
    ).fetchall()
    meus = []
    for r in donos:
        p = r[0]
        compart = conn.execute("""
            SELECT c.shared_with_id, u.nome, u.email, u.username
            FROM pdf_compartilhamentos c
            JOIN users u ON u.id = c.shared_with_id
            WHERE c.pdf_path = ?
            ORDER BY u.nome
        """, (p,)).fetchall()
        meus.append({
            "path": p,
            "nome": p.split("/")[-1],
            "compartilhado_com": [
                {"user_id": c[0], "nome": c[1], "email": c[2], "username": c[3]} for c in compart
            ],
        })

    # PDFs compartilhados comigo
    comigo_rows = conn.execute("""
        SELECT c.pdf_path, c.owner_id, u.nome, u.email, u.username
        FROM pdf_compartilhamentos c
        JOIN users u ON u.id = c.owner_id
        WHERE c.shared_with_id = ?
        ORDER BY c.pdf_path
    """, (user_id,)).fetchall()
    comigo = [{
        "path": r[0],
        "nome": r[0].split("/")[-1],
        "dono": {"user_id": r[1], "nome": r[2], "email": r[3], "username": r[4]},
    } for r in comigo_rows]

    return {"meus": meus, "compartilhados_comigo": comigo}


@router.post("/api/pdf/compartilhar", summary="Compartilhar um PDF com outro usuário")
def compartilhar_pdf(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Compartilha um PDF com outro usuário.

    body: {pdf_path: str, destino: str}  # destino = id, email ou username

    Regras:
    - PDF com dono: apenas o dono (ou um admin) pode compartilhar.
    - PDF órfão (sem dono): apenas um admin pode agir; ao compartilhar, o admin
      passa a ser registrado como dono do arquivo.
    """
    from datetime import datetime, timezone

    pdf_path = (body.get("pdf_path") or "").strip()
    destino = body.get("destino")
    if not pdf_path:
        raise HTTPException(status_code=400, detail="pdf_path é obrigatório")
    if not destino:
        raise HTTPException(status_code=400, detail="destino (id/email/username) é obrigatório")

    now = datetime.now(timezone.utc).isoformat()
    is_admin = _is_admin(conn, user_id)
    owner_id = get_owner_id(conn, pdf_path)

    if owner_id is None:
        # PDF órfão: só admin pode agir e assume a propriedade.
        if not is_admin:
            raise HTTPException(status_code=404, detail="PDF não encontrado ou sem dono registrado")
        # Valida que o arquivo existe no disco antes de registrar dono
        if PDF_ROOT and ".." not in pdf_path and not pdf_path.startswith("/"):  # noqa: SIM102 (comentário entre os ifs; fundir reduz clareza)
            if not (Path(PDF_ROOT) / pdf_path).exists():
                raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado no disco")
        conn.execute(
            "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, ?, ?)",
            (pdf_path, user_id, now)
        )
        owner_id = user_id
    elif owner_id != user_id and not is_admin:
        raise HTTPException(status_code=403, detail="Apenas o dono pode compartilhar este PDF")

    alvo = _resolve_user(conn, destino)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuário destino não encontrado")
    if alvo[0] == owner_id:
        raise HTTPException(status_code=400, detail="O destino já é o dono deste PDF")

    conn.execute("""
        INSERT OR IGNORE INTO pdf_compartilhamentos (pdf_path, owner_id, shared_with_id, created_at)
        VALUES (?, ?, ?, ?)
    """, (pdf_path, owner_id, alvo[0], now))
    conn.commit()
    return {
        "ok": True,
        "pdf_path": pdf_path,
        "compartilhado_com": {"user_id": alvo[0], "nome": alvo[1], "email": alvo[2], "username": alvo[3]},
    }


@router.post("/api/pdf/descompartilhar", summary="Remover compartilhamento de um PDF")
def descompartilhar_pdf(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Remove o acesso de um usuário a um PDF.

    body: {pdf_path: str, destino: str}
    Só o dono pode revogar acessos concedidos.
    """
    pdf_path = (body.get("pdf_path") or "").strip()
    destino = body.get("destino")
    if not pdf_path or not destino:
        raise HTTPException(status_code=400, detail="pdf_path e destino são obrigatórios")

    owner_id = get_owner_id(conn, pdf_path)
    if owner_id is None:
        raise HTTPException(status_code=404, detail="PDF não encontrado ou sem dono registrado")
    if owner_id != user_id and not _is_admin(conn, user_id):
        raise HTTPException(status_code=403, detail="Apenas o dono pode remover compartilhamentos")

    alvo = _resolve_user(conn, destino)
    if not alvo:
        raise HTTPException(status_code=404, detail="Usuário destino não encontrado")

    conn.execute(
        "DELETE FROM pdf_compartilhamentos WHERE pdf_path = ? AND shared_with_id = ?",
        (pdf_path, alvo[0])
    )
    conn.commit()
    return {"ok": True, "pdf_path": pdf_path, "removido": alvo[0]}


# ==================== ADMIN: PDFs ÓRFÃOS ====================

@router.get("/api/pdf/orfaos", summary="[Admin] Listar PDFs sem dono",
            description="Lista os PDFs presentes no disco que ainda não têm dono registrado.")
def listar_orfaos(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Só administradores enxergam PDFs órfãos (para atribuir dono/compartilhar)."""
    if not _is_admin(conn, user_id):
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")
    orfaos = sorted(_orphan_paths(conn))
    return {"orfaos": [{"path": p, "nome": p.split("/")[-1]} for p in orfaos], "total": len(orfaos)}


@router.post("/api/pdf/definir-dono", summary="[Admin] Definir o dono de um PDF",
             description="Atribui (ou reatribui) o dono de um PDF. Restrito a administradores.")
def definir_dono(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Define o dono de um PDF (por id/email/username do novo dono).

    body: {pdf_path: str, dono: str}
    Restrito a admin — usado principalmente para adotar PDFs órfãos.
    """
    from datetime import datetime, timezone

    if not _is_admin(conn, user_id):
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")

    pdf_path = (body.get("pdf_path") or "").strip()
    dono = body.get("dono")
    if not pdf_path or not dono:
        raise HTTPException(status_code=400, detail="pdf_path e dono são obrigatórios")

    # Valida que o arquivo existe no disco
    if ".." in pdf_path or pdf_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Caminho inválido")
    if PDF_ROOT and not (Path(PDF_ROOT) / pdf_path).exists():
        raise HTTPException(status_code=404, detail="Arquivo PDF não encontrado no disco")

    novo_dono = _resolve_user(conn, dono)
    if not novo_dono:
        raise HTTPException(status_code=404, detail="Usuário (novo dono) não encontrado")

    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, ?, ?)",
        (pdf_path, novo_dono[0], now)
    )
    # Se o novo dono estava como destino de compartilhamento, remove (agora é dono)
    conn.execute(
        "DELETE FROM pdf_compartilhamentos WHERE pdf_path = ? AND shared_with_id = ?",
        (pdf_path, novo_dono[0])
    )
    # Auditoria (best-effort)
    try:
        conn.execute(
            "INSERT INTO admin_audit (admin_id, acao, alvo_tipo, alvo_id, detalhe, created_at) "
            "VALUES (?, 'pdf.definir_dono', 'pdf', ?, ?, ?)",
            (user_id, pdf_path, f'{{"novo_dono": {novo_dono[0]}}}', now)
        )
    except Exception:
        pass
    conn.commit()
    return {
        "ok": True,
        "pdf_path": pdf_path,
        "dono": {"user_id": novo_dono[0], "nome": novo_dono[1], "email": novo_dono[2], "username": novo_dono[3]},
    }

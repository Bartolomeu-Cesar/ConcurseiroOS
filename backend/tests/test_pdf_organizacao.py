"""
Testes da organização virtual de PDFs (pastas virtuais + drag & drop).

Cobre os endpoints usados pelo "Modo Organizar":
- POST   /api/pdf/pastas         → criar pasta virtual
- POST   /api/pdf/mover          → mover PDF para pasta (ou raiz se id=null)
- GET    /api/pdf/organizacao    → árvore com overlay de organização
- PUT    /api/pdf/pastas/{id}    → renomear
- DELETE /api/pdf/pastas/{id}    → excluir (PDFs voltam para raiz)

Regressão principal: mover um PDF para uma pasta deve fazê-lo aparecer DENTRO
da pasta na organização (o bug de drag&drop no frontend era o evento borbulhar
até a raiz e mover de volta; aqui garantimos que o backend persiste corretamente).

Executar: pytest tests/test_pdf_organizacao.py -v
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_pdf_org.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient

from deps import get_user_id
from main import app
from routers import pdf as pdf_module


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)

# PDF_ROOT temporário com PDFs reais na RAIZ (onde build_tree gera path == name,
# igual ao que o frontend arrasta em data-pdf-path).
_pdf_root = tempfile.mkdtemp(prefix="pdfroot_org_")
Path(_pdf_root, "aula1.pdf").write_bytes(b"%PDF-1.4 a1")
Path(_pdf_root, "aula2.pdf").write_bytes(b"%PDF-1.4 a2")

_PATH_A1 = "aula1.pdf"
_PATH_A2 = "aula2.pdf"
_UID = 10


def _override_user_id(uid):
    async def override():
        return uid
    return override


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_user_id] = _override_user_id(_UID)
    pdf_module.PDF_ROOT = _pdf_root
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    # Limpa organização entre testes para isolamento.
    conn.execute("DELETE FROM pdf_organizacao")
    conn.execute("DELETE FROM pdf_pastas_virtuais")
    # Registra o usuário de teste como dono dos PDFs (política fail-closed de
    # visibilidade: um PDF só aparece na árvore se o usuário for dono/compartilhado).
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at) VALUES (?, 'Dono', 'dono@t.com', 'dono', ?)",
        (_UID, now),
    )
    for p in (_PATH_A1, _PATH_A2):
        conn.execute(
            "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, ?, ?)",
            (p, _UID, now),
        )
    conn.commit()
    conn.close()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def _criar_pasta(nome):
    r = client.post("/api/pdf/pastas", json={"nome": nome})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _find_folder(tree, pasta_id):
    for n in tree:
        if n.get("type") == "folder" and n.get("id") == pasta_id:
            return n
    return None


def _pdf_paths_in(node):
    """Coleta os paths de PDFs (recursivo) dentro de um nó/lista."""
    out = []
    children = node.get("children", []) if isinstance(node, dict) else node
    for c in children:
        if c.get("type") == "pdf":
            out.append(c.get("path") or c.get("name"))
        elif c.get("type") == "folder":
            out.extend(_pdf_paths_in(c))
    return out


# ==================== CRIAR PASTA ====================

def test_criar_pasta_virtual():
    pid = _criar_pasta("Revisão")
    assert isinstance(pid, int)
    r = client.get("/api/pdf/organizacao")
    assert r.status_code == 200
    data = r.json()
    assert data["organizado"] is True
    assert _find_folder(data["tree"], pid) is not None


def test_criar_pasta_sem_nome_falha():
    r = client.post("/api/pdf/pastas", json={"nome": "  "})
    assert r.status_code == 400


# ==================== MOVER (REGRESSÃO PRINCIPAL) ====================

def test_mover_pdf_para_pasta_aparece_dentro():
    pid = _criar_pasta("Estudar")
    r = client.post("/api/pdf/mover", json={"pdf_path": _PATH_A1, "pasta_virtual_id": pid})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    data = client.get("/api/pdf/organizacao").json()
    pasta = _find_folder(data["tree"], pid)
    assert pasta is not None
    dentro = _pdf_paths_in(pasta)
    assert _PATH_A1 in dentro, f"PDF deveria estar na pasta {pid}, children={dentro}"
    # E NÃO deve estar solto na raiz.
    raiz_pdfs = [n.get("path") or n.get("name") for n in data["tree"] if n.get("type") == "pdf"]
    assert _PATH_A1 not in raiz_pdfs


def test_mover_pdf_persiste_no_banco():
    pid = _criar_pasta("Persistente")
    client.post("/api/pdf/mover", json={"pdf_path": _PATH_A1, "pasta_virtual_id": pid})
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    row = conn.execute(
        "SELECT pasta_virtual_id FROM pdf_organizacao WHERE pdf_path = ? AND user_id = ?",
        (_PATH_A1, _UID),
    ).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == pid


def test_mover_pdf_para_raiz_remove_da_pasta():
    pid = _criar_pasta("Temp")
    client.post("/api/pdf/mover", json={"pdf_path": _PATH_A1, "pasta_virtual_id": pid})
    # Move de volta para raiz (pasta_virtual_id = null)
    r = client.post("/api/pdf/mover", json={"pdf_path": _PATH_A1, "pasta_virtual_id": None})
    assert r.status_code == 200

    data = client.get("/api/pdf/organizacao").json()
    pasta = _find_folder(data["tree"], pid)
    assert _PATH_A1 not in _pdf_paths_in(pasta or {})
    raiz_pdfs = [n.get("path") or n.get("name") for n in data["tree"] if n.get("type") == "pdf"]
    assert _PATH_A1 in raiz_pdfs


def test_mover_re_mover_entre_pastas():
    """Mover para pasta A, depois para pasta B — deve ficar só em B (bug do bubbling)."""
    pa = _criar_pasta("Pasta A")
    pb = _criar_pasta("Pasta B")
    client.post("/api/pdf/mover", json={"pdf_path": _PATH_A2, "pasta_virtual_id": pa})
    client.post("/api/pdf/mover", json={"pdf_path": _PATH_A2, "pasta_virtual_id": pb})

    data = client.get("/api/pdf/organizacao").json()
    assert _PATH_A2 not in _pdf_paths_in(_find_folder(data["tree"], pa) or {})
    assert _PATH_A2 in _pdf_paths_in(_find_folder(data["tree"], pb) or {})


def test_mover_sem_pdf_path_falha():
    r = client.post("/api/pdf/mover", json={"pdf_path": "  ", "pasta_virtual_id": None})
    assert r.status_code == 400


# ==================== RENOMEAR / EXCLUIR ====================

def test_renomear_pasta():
    pid = _criar_pasta("Antigo")
    r = client.put(f"/api/pdf/pastas/{pid}", json={"nome": "Novo"})
    assert r.status_code == 200
    data = client.get("/api/pdf/organizacao").json()
    assert _find_folder(data["tree"], pid)["name"] == "Novo"


def test_excluir_pasta_pdf_volta_para_raiz():
    pid = _criar_pasta("Descartável")
    client.post("/api/pdf/mover", json={"pdf_path": _PATH_A1, "pasta_virtual_id": pid})
    r = client.delete(f"/api/pdf/pastas/{pid}")
    assert r.status_code == 200
    data = client.get("/api/pdf/organizacao").json()
    # Pasta sumiu; PDF voltou para raiz.
    assert _find_folder(data["tree"], pid) is None
    raiz_pdfs = [n.get("path") or n.get("name") for n in data["tree"] if n.get("type") == "pdf"]
    assert _PATH_A1 in raiz_pdfs

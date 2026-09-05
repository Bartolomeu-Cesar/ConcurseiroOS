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

from deps import get_user_id
from fastapi.testclient import TestClient
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

# PDF_ROOT temporário. Agora build_tree gera path COMPLETO relativo à raiz
# (ex.: "Direito/aula1.pdf"), igual ao que o frontend arrasta em data-pdf-path
# e ao que serve_pdf resolve (PDF_ROOT / path).
_pdf_root = tempfile.mkdtemp(prefix="pdfroot_org_")
Path(_pdf_root, "aula1.pdf").write_bytes(b"%PDF-1.4 a1")
Path(_pdf_root, "aula2.pdf").write_bytes(b"%PDF-1.4 a2")
# PDFs em subpastas — o cenário que reproduz o bug de path relativo à subpasta.
Path(_pdf_root, "Direito").mkdir(parents=True, exist_ok=True)
Path(_pdf_root, "Portugues").mkdir(parents=True, exist_ok=True)
Path(_pdf_root, "Direito", "aula1.pdf").write_bytes(b"%PDF-1.4 dir")   # nome duplicado!
Path(_pdf_root, "Portugues", "aula1.pdf").write_bytes(b"%PDF-1.4 port")  # nome duplicado!
Path(_pdf_root, "Direito", "constituicao.pdf").write_bytes(b"%PDF-1.4 const")

_PATH_A1 = "aula1.pdf"
_PATH_A2 = "aula2.pdf"
_PATH_DIR_A1 = "Direito/aula1.pdf"
_PATH_PORT_A1 = "Portugues/aula1.pdf"
_PATH_DIR_CONST = "Direito/constituicao.pdf"
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
    for p in (_PATH_A1, _PATH_A2, _PATH_DIR_A1, _PATH_PORT_A1, _PATH_DIR_CONST):
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


# ==================== REGRESSÃO: PDF EM SUBPASTA (path completo) ====================

def test_build_tree_gera_path_completo():
    """build_tree deve gerar path relativo à RAIZ, não à subpasta imediata."""
    from utils import build_tree
    paths = []

    def _walk(nodes):
        for n in nodes:
            if n["type"] == "pdf":
                paths.append(n["path"])
            else:
                _walk(n.get("children", []))
    _walk(build_tree(_pdf_root))
    assert _PATH_DIR_A1 in paths, f"esperava '{_PATH_DIR_A1}', paths={paths}"
    assert _PATH_PORT_A1 in paths, f"esperava '{_PATH_PORT_A1}', paths={paths}"
    # Nomes duplicados em pastas diferentes NÃO colidem (paths distintos).
    assert paths.count("aula1.pdf") == 1  # só o da raiz tem esse path exato


def test_mover_pdf_de_subpasta_aparece_na_pasta_virtual():
    """Regressão do bug relatado: PDF em subpasta arrastado não saía do lugar.

    Com path completo, mover 'Direito/constituicao.pdf' para uma pasta virtual
    deve funcionar exatamente como um PDF da raiz.
    """
    pid = _criar_pasta("Revisão Direito")
    r = client.post("/api/pdf/mover", json={"pdf_path": _PATH_DIR_CONST, "pasta_virtual_id": pid})
    assert r.status_code == 200, r.text

    data = client.get("/api/pdf/organizacao").json()
    pasta = _find_folder(data["tree"], pid)
    assert pasta is not None
    assert _PATH_DIR_CONST in _pdf_paths_in(pasta), \
        f"PDF de subpasta deveria estar na pasta {pid}, children={_pdf_paths_in(pasta)}"


def test_mover_nomes_duplicados_em_pastas_diferentes():
    """Dois PDFs 'aula1.pdf' (Direito e Portugues) devem ser movíveis de forma
    independente — o bug de colisão de path movia/sumia o PDF errado."""
    pd = _criar_pasta("Só Direito")
    # Move apenas o de Direito.
    r = client.post("/api/pdf/mover", json={"pdf_path": _PATH_DIR_A1, "pasta_virtual_id": pd})
    assert r.status_code == 200, r.text

    data = client.get("/api/pdf/organizacao").json()
    pasta = _find_folder(data["tree"], pd)
    dentro = _pdf_paths_in(pasta)
    # O de Direito está na pasta; o de Portugues NÃO (não colidiu).
    assert _PATH_DIR_A1 in dentro, f"children={dentro}"
    assert _PATH_PORT_A1 not in dentro, f"colisão! children={dentro}"

    # E o de Portugues continua acessível fora da pasta (na árvore real).
    all_paths = _pdf_paths_in(data["tree"])
    assert _PATH_PORT_A1 in all_paths


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

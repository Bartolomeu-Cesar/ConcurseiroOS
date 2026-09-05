"""
Testes do contrato de re-leitura de /api/tree usado pelo botão "🔄 Sincronizar".

Ao trocar de estação de trabalho, a pasta de PDFs pode mudar de conteúdo. O botão
Sincronizar (modo servidor) simplesmente rechama GET /api/tree, e o backend relê o
disco (build_tree(PDF_ROOT)) a cada chamada — sem cache. Estes testes garantem esse
contrato:

- Adicionar um PDF novo ao PDF_ROOT (com dono registrado) faz ele aparecer numa
  nova chamada a /api/tree, sem reiniciar o servidor.
- Remover um PDF do disco faz ele sumir da listagem numa nova chamada.

Executar: pytest tests/test_pdf_sincronizar.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_pdf_sync.db", delete=False)
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

# PDF_ROOT temporário com um PDF inicial na raiz.
_pdf_root = tempfile.mkdtemp(prefix="pdfroot_sync_")
Path(_pdf_root, "inicial.pdf").write_bytes(b"%PDF-1.4 inicial")

_UID = 20


def _override_user_id(uid):
    async def override():
        return uid
    return override


def _now():
    return datetime.now(timezone.utc).isoformat()


def _registrar_dono(path):
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, ?, ?)",
        (path, _UID, _now()),
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    # Salva overrides anteriores para restaurar no teardown (evita vazar estado
    # global do app — ex.: get_user_id — para outros arquivos de teste).
    _prev = dict(app.dependency_overrides)
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_user_id] = _override_user_id(_UID)
    pdf_module.PDF_ROOT = _pdf_root
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at) VALUES (?, 'Dono', 'dono@sync.com', 'donosync', ?)",
        (_UID, _now()),
    )
    conn.commit()
    conn.close()
    _registrar_dono("inicial.pdf")
    yield
    # Teardown: restaura o estado anterior dos overrides.
    app.dependency_overrides.clear()
    app.dependency_overrides.update(_prev)


def _nomes_da_arvore(tree):
    """Extrai recursivamente os nomes de PDFs da árvore retornada por /api/tree."""
    nomes = []
    for n in tree:
        if n.get("type") == "pdf":
            nomes.append(n.get("name"))
        elif n.get("type") == "folder":
            nomes.extend(_nomes_da_arvore(n.get("children", [])))
    return nomes


def test_tree_reflete_pdf_adicionado_sem_reiniciar():
    """Adicionar um PDF ao disco aparece numa nova chamada a /api/tree (Sincronizar)."""
    r1 = client.get("/api/tree")
    assert r1.status_code == 200
    assert "inicial.pdf" in _nomes_da_arvore(r1.json())

    # Simula o usuário colocando um novo PDF na pasta (nova estação/pasta atualizada).
    Path(_pdf_root, "novo.pdf").write_bytes(b"%PDF-1.4 novo")
    _registrar_dono("novo.pdf")

    # Sincronizar = rechamar /api/tree; backend relê o disco.
    r2 = client.get("/api/tree")
    assert r2.status_code == 200
    nomes = _nomes_da_arvore(r2.json())
    assert "novo.pdf" in nomes, "PDF adicionado deveria aparecer após re-leitura"
    assert "inicial.pdf" in nomes

    # Limpeza para não interferir em outros testes.
    Path(_pdf_root, "novo.pdf").unlink(missing_ok=True)


def test_tree_reflete_pdf_removido_sem_reiniciar():
    """Remover um PDF do disco some da listagem numa nova chamada a /api/tree."""
    Path(_pdf_root, "temporario.pdf").write_bytes(b"%PDF-1.4 temp")
    _registrar_dono("temporario.pdf")

    r1 = client.get("/api/tree")
    assert "temporario.pdf" in _nomes_da_arvore(r1.json())

    Path(_pdf_root, "temporario.pdf").unlink(missing_ok=True)

    r2 = client.get("/api/tree")
    assert "temporario.pdf" not in _nomes_da_arvore(r2.json()), (
        "PDF removido do disco não deveria mais aparecer após re-leitura"
    )

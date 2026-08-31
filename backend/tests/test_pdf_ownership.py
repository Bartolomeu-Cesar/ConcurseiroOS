"""
Testes de visibilidade/compartilhamento de PDFs (feature de ownership).

Arquivos são globais no disco; a visibilidade é controlada por metadados:
- dono vê seus PDFs;
- terceiro (sem acesso) NÃO vê;
- usuário compartilhado vê;
- progresso é independente por usuário (PK path+user_id);
- só o dono apaga o arquivo físico; não-dono só descompartilha.

Executar: pytest tests/test_pdf_ownership.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_pdf_owner.db", delete=False)
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

# PDF_ROOT temporário com PDFs reais.
_pdf_root = tempfile.mkdtemp(prefix="pdfroot_owner_")
Path(_pdf_root, "MateriaA").mkdir(parents=True, exist_ok=True)
Path(_pdf_root, "MateriaA", "dono.pdf").write_bytes(b"%PDF-1.4 dono")
Path(_pdf_root, "MateriaA", "compartilhado.pdf").write_bytes(b"%PDF-1.4 compart")
Path(_pdf_root, "legado.pdf").write_bytes(b"%PDF-1.4 legado")

_PATH_DONO = "MateriaA/dono.pdf"
_PATH_COMPART = "MateriaA/compartilhado.pdf"
_PATH_LEGADO = "legado.pdf"


def _override_user_id(uid):
    async def override():
        return uid
    return override


def _seed():
    """Cria usuários 10/20/30 e registra donos dos PDFs de teste."""
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    now = datetime.now(timezone.utc).isoformat()
    for uid, nome, email, uname in [
        (10, "Dono", "dono@t.com", "dono"),
        (20, "Amigo", "amigo@t.com", "amigo"),
        (30, "Terceiro", "terceiro@t.com", "terceiro"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, nome, email, username, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, nome, email, uname, now),
        )
    # PDFs 'dono.pdf' e 'compartilhado.pdf' pertencem ao uid 10.
    # 'legado.pdf' fica SEM dono (fail-open).
    for p in (_PATH_DONO, _PATH_COMPART):
        conn.execute(
            "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, 10, ?)",
            (p, now),
        )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    pdf_module.PDF_ROOT = _pdf_root
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


# ==================== VISIBILIDADE ====================

def test_dono_ve_pdf():
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    r = client.get(f"/pdf/{_PATH_DONO}")
    assert r.status_code == 200


def test_terceiro_nao_ve_pdf():
    app.dependency_overrides[get_user_id] = _override_user_id(30)
    r = client.get(f"/pdf/{_PATH_DONO}")
    assert r.status_code == 403


def test_pdf_existe_respeita_visibilidade():
    app.dependency_overrides[get_user_id] = _override_user_id(30)
    r = client.get(f"/api/pdf-existe/{_PATH_DONO}")
    assert r.status_code == 200
    assert r.json() == {"existe": False}


def test_pdf_legado_sem_dono_e_visivel():
    """PDF sem dono registrado é fail-open (legado ainda não indexado)."""
    app.dependency_overrides[get_user_id] = _override_user_id(30)
    r = client.get(f"/pdf/{_PATH_LEGADO}")
    assert r.status_code == 200


def test_tree_filtra_por_visibilidade():
    # Terceiro não vê os PDFs do dono, mas vê o legado (sem dono).
    app.dependency_overrides[get_user_id] = _override_user_id(30)
    r = client.get("/api/tree")
    assert r.status_code == 200
    paths = _flatten_paths(r.json())
    assert _PATH_DONO not in paths
    assert _PATH_COMPART not in paths
    assert _PATH_LEGADO in paths


def _flatten_paths(nodes):
    out = []
    for n in nodes:
        if n.get("type") == "pdf":
            out.append(n.get("path"))
        elif n.get("type") == "folder":
            out.extend(_flatten_paths(n.get("children", [])))
    return out


# ==================== COMPARTILHAMENTO ====================

def test_compartilhar_e_amigo_passa_a_ver():
    # Dono compartilha compartilhado.pdf com o amigo (por email).
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    r = client.post("/api/pdf/compartilhar", json={"pdf_path": _PATH_COMPART, "destino": "amigo@t.com"})
    assert r.status_code == 200, r.text
    assert r.json()["compartilhado_com"]["user_id"] == 20

    # Agora o amigo vê.
    app.dependency_overrides[get_user_id] = _override_user_id(20)
    r = client.get(f"/pdf/{_PATH_COMPART}")
    assert r.status_code == 200

    # Terceiro continua sem ver.
    app.dependency_overrides[get_user_id] = _override_user_id(30)
    r = client.get(f"/pdf/{_PATH_COMPART}")
    assert r.status_code == 403


def test_terceiro_nao_pode_compartilhar_pdf_alheio():
    app.dependency_overrides[get_user_id] = _override_user_id(30)
    r = client.post("/api/pdf/compartilhar", json={"pdf_path": _PATH_DONO, "destino": "amigo"})
    assert r.status_code == 403


def test_descompartilhar_revoga_acesso():
    # Dono compartilha e depois revoga.
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    client.post("/api/pdf/compartilhar", json={"pdf_path": _PATH_DONO, "destino": "amigo"})

    app.dependency_overrides[get_user_id] = _override_user_id(20)
    assert client.get(f"/pdf/{_PATH_DONO}").status_code == 200

    app.dependency_overrides[get_user_id] = _override_user_id(10)
    r = client.post("/api/pdf/descompartilhar", json={"pdf_path": _PATH_DONO, "destino": "amigo"})
    assert r.status_code == 200

    app.dependency_overrides[get_user_id] = _override_user_id(20)
    assert client.get(f"/pdf/{_PATH_DONO}").status_code == 403


def test_meus_pdfs_lista_donos_e_compartilhados():
    # Dono compartilha compartilhado.pdf com amigo.
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    client.post("/api/pdf/compartilhar", json={"pdf_path": _PATH_COMPART, "destino": "amigo"})

    r = client.get("/api/pdf/meus")
    assert r.status_code == 200
    data = r.json()
    meus_paths = {m["path"] for m in data["meus"]}
    assert _PATH_DONO in meus_paths and _PATH_COMPART in meus_paths

    # Do lado do amigo: aparece em compartilhados_comigo.
    app.dependency_overrides[get_user_id] = _override_user_id(20)
    r = client.get("/api/pdf/meus")
    comigo = {c["path"] for c in r.json()["compartilhados_comigo"]}
    assert _PATH_COMPART in comigo


# ==================== PROGRESSO POR USUÁRIO ====================

def test_progresso_independente_por_usuario():
    # Dono compartilha para o amigo poder acessar/registrar progresso.
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    client.post("/api/pdf/compartilhar", json={"pdf_path": _PATH_COMPART, "destino": "amigo"})

    # Dono salva progresso página 5.
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    r = client.post(f"/api/progress/{_PATH_COMPART}", json={"current_page": 5, "total_pages": 100})
    assert r.status_code == 200

    # Amigo salva progresso página 42 no MESMO arquivo.
    app.dependency_overrides[get_user_id] = _override_user_id(20)
    r = client.post(f"/api/progress/{_PATH_COMPART}", json={"current_page": 42, "total_pages": 100})
    assert r.status_code == 200

    # Cada um mantém seu próprio progresso.
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    assert client.get(f"/api/progress/{_PATH_COMPART}").json()["current_page"] == 5
    app.dependency_overrides[get_user_id] = _override_user_id(20)
    assert client.get(f"/api/progress/{_PATH_COMPART}").json()["current_page"] == 42


# ==================== DELETE ====================

def test_nao_dono_apenas_descompartilha_sem_apagar_arquivo():
    # Cria PDF próprio p/ este teste e compartilha com amigo.
    Path(_pdf_root, "MateriaA", "del.pdf").write_bytes(b"%PDF-1.4 del")
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, 10, ?)",
        ("MateriaA/del.pdf", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    app.dependency_overrides[get_user_id] = _override_user_id(10)
    client.post("/api/pdf/compartilhar", json={"pdf_path": "MateriaA/del.pdf", "destino": "amigo"})

    # Amigo "exclui" — só perde o próprio acesso, arquivo permanece.
    app.dependency_overrides[get_user_id] = _override_user_id(20)
    r = client.delete("/api/pdfs/MateriaA/del.pdf")
    assert r.status_code == 200
    assert r.json()["arquivo_apagado"] is False
    assert Path(_pdf_root, "MateriaA", "del.pdf").exists()

    # Dono ainda vê.
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    assert client.get("/pdf/MateriaA/del.pdf").status_code == 200


def test_dono_apaga_arquivo_fisico():
    Path(_pdf_root, "MateriaA", "del2.pdf").write_bytes(b"%PDF-1.4 del2")
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute(
        "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, 10, ?)",
        ("MateriaA/del2.pdf", datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    app.dependency_overrides[get_user_id] = _override_user_id(10)
    r = client.delete("/api/pdfs/MateriaA/del2.pdf")
    assert r.status_code == 200
    assert r.json()["arquivo_apagado"] is True
    assert not Path(_pdf_root, "MateriaA", "del2.pdf").exists()

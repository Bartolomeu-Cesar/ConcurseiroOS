"""Testa o serve_pdf com autenticação flexível (header OU query ?token=).

Contexto: o PDF.js embutido carrega a URL do PDF diretamente no iframe e o
navegador NÃO anexa o header Authorization. Por isso o viewer passa o token
via query string, aceito por get_user_id_flexible. Estes testes garantem:

- sem token            → 401;
- token válido (query) → 200 + application/pdf (dono do arquivo);
- token inválido       → 401;
- token válido (header)→ 200 (compatibilidade com o header tradicional);
- terceiro sem acesso  → 403 (ownership fail-closed).

Executar: pytest tests/test_pdf_serve_token.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_pdf_serve_token.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "true"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

import jwt
from fastapi.testclient import TestClient

from main import app
from routers import pdf as pdf_module
from settings import settings
from deps import get_user_id

# AUTH_ENABLED é reafirmado por teste na fixture autouse (_isolar_estado), para
# não poluir o estado global compartilhado no momento do import.


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

# PDF_ROOT temporário com um PDF real (dono = user 10).
_pdf_root = tempfile.mkdtemp(prefix="pdfroot_servetoken_")
Path(_pdf_root, "Materia").mkdir(parents=True, exist_ok=True)
Path(_pdf_root, "Materia", "aula.pdf").write_bytes(b"%PDF-1.4 conteudo de teste\n%%EOF")
pdf_module.set_pdf_root(_pdf_root)

_PATH = "Materia/aula.pdf"


@pytest.fixture(autouse=True)
def _isolar_estado():
    """Reafirma estado global antes de cada teste (robustez a ordenação da suíte).

    Outros módulos de teste alteram settings.AUTH_ENABLED / PDF_ROOT / DB_PATH e
    dependency_overrides no import. Como o objeto `settings` e o `app` são
    singletons compartilhados, precisamos reafirmar o estado esperado aqui e
    limpar overrides de get_user_id que outros módulos possam ter deixado.
    """
    database.DB_PATH = _tmp_db.name
    settings.AUTH_ENABLED = True
    pdf_module.set_pdf_root(_pdf_root)
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides.pop(get_user_id, None)
    yield
    settings.AUTH_ENABLED = False
    app.dependency_overrides.pop(get_user_id, None)


def _seed():
    conn = sqlite3.connect(_tmp_db.name, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=10000")
    now = datetime.now(timezone.utc).isoformat()
    for uid, nome, email, uname in [
        (10, "Dono", "dono@t.com", "dono"),
        (30, "Terceiro", "terceiro@t.com", "terceiro"),
    ]:
        conn.execute(
            "INSERT OR IGNORE INTO users (id, nome, email, username, created_at) VALUES (?, ?, ?, ?, ?)",
            (uid, nome, email, uname, now),
        )
    conn.execute(
        "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, ?, ?)",
        (_PATH, 10, now),
    )
    conn.commit()
    conn.close()


def _token(uid: int) -> str:
    return jwt.encode({"sub": str(uid), "type": "access"}, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def test_sem_token_401():
    _seed()
    r = client.get(f"/pdf/{_PATH}")
    assert r.status_code == 401, r.text


def test_token_query_valido_dono_200():
    _seed()
    r = client.get(f"/pdf/{_PATH}?token={_token(10)}")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_token_query_invalido_401():
    _seed()
    r = client.get(f"/pdf/{_PATH}?token=nao-e-um-jwt")
    assert r.status_code == 401, r.text


def test_token_header_ainda_funciona_200():
    """Compatibilidade: o header Authorization tradicional continua aceito."""
    _seed()
    r = client.get(f"/pdf/{_PATH}", headers={"Authorization": f"Bearer {_token(10)}"})
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"%PDF")


def test_terceiro_com_token_query_403():
    """PDF de outro dono → 403 (ownership fail-closed), mesmo com token válido."""
    _seed()
    r = client.get(f"/pdf/{_PATH}?token={_token(30)}")
    assert r.status_code == 403, r.text

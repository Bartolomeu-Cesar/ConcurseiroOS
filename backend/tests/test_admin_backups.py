"""
Testes de gestão de backups pela UI/admin (/api/backups*).

Usa BACKUP_DIR temporário e DB temporário. Verifica: role admin obrigatória,
criar/listar/baixar/deletar backup, e auditoria das ações.

Executar: pytest tests/test_admin_backups.py -v
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_admin_backup.db", delete=False)
_tmp_db.close()
_bkp_dir = tempfile.mkdtemp(prefix="backups_test_")

os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["BACKUP_DIR"] = _bkp_dir
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import settings as settings_mod
from database import get_db_session

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
settings_mod.settings.BACKUP_DIR = _bkp_dir
database.init_db()

# backup.py leu BACKUP_DIR no import — realinhar para o dir de teste
from pathlib import Path as _Path

import backup as backup_mod

backup_mod.BACKUP_DIR = _Path(_bkp_dir)

from deps import get_user_id
from fastapi.testclient import TestClient
from main import app


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


def _override_user_id(uid):
    async def override():
        return uid
    return override


def _seed():
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    now = datetime.now(timezone.utc).isoformat()
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (1,'Admin','a@t.com','admin',?, 'admin')",
        (now,),
    )
    conn.execute("UPDATE users SET role='admin' WHERE id=1")
    conn.execute(
        "INSERT OR IGNORE INTO users (id, nome, email, username, created_at, role) VALUES (55,'Comum','c@t.com','comum',?, 'user')",
        (now,),
    )
    conn.commit()
    conn.close()


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    settings_mod.settings.DB_PATH = _tmp_db.name
    settings_mod.settings.BACKUP_DIR = _bkp_dir
    backup_mod.BACKUP_DIR = _Path(_bkp_dir)
    app.dependency_overrides[get_db_session] = _override_db_session
    _seed()
    yield
    app.dependency_overrides.pop(get_user_id, None)


def test_nao_admin_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(55)
    assert client.get("/api/backups").status_code == 403
    assert client.post("/api/backups").status_code == 403


def test_criar_listar_baixar_deletar():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    # Criar
    r = client.post("/api/backups")
    assert r.status_code == 200, r.text
    fname = r.json()["filename"]
    assert fname.endswith(".db")

    # Listar
    r = client.get("/api/backups")
    assert r.status_code == 200
    nomes = [b["filename"] for b in r.json()]
    assert fname in nomes

    # Baixar
    r = client.get(f"/api/backups/download/{fname}")
    assert r.status_code == 200
    assert len(r.content) > 0

    # Deletar
    r = client.delete(f"/api/backups/{fname}")
    assert r.status_code == 200
    r = client.get("/api/backups")
    assert fname not in [b["filename"] for b in r.json()]


def test_download_traversal_bloqueado():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    r = client.get("/api/backups/download/..%2F..%2Fetc%2Fpasswd")
    assert r.status_code in (400, 404)


def test_backup_auditado():
    app.dependency_overrides[get_user_id] = _override_user_id(1)
    client.post("/api/backups")
    r = client.get("/api/admin/auditoria?acao=backup")
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(it["acao"] == "backup.criar" for it in items)

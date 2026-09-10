"""Testes de GET /api/progress-resumo/{path} — cartão "continuar de onde parou".

Reúne progresso (página/percentual/última leitura) + contagens de material de
estudo do usuário (notas, bookmarks, destaques, blocos de revisão) numa chamada.

Base isolada (TEST_DB), AUTH_ENABLED=false → user 1. PDF com dono registrado
(política fail-closed exige dono).
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_progresumo.db", delete=False)
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
from main import app
from routers import pdf as pdf_module


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)

_pdf_root = tempfile.mkdtemp(prefix="pdfroot_resumo_")
Path(_pdf_root, "Materia").mkdir(parents=True, exist_ok=True)
Path(_pdf_root, "Materia", "aula.pdf").write_bytes(b"%PDF-1.4 fake")
Path(_pdf_root, "Materia", "novo.pdf").write_bytes(b"%PDF-1.4 fake")

_PATH = "Materia/aula.pdf"
_PATH_NOVO = "Materia/novo.pdf"


def _conn():
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    c.row_factory = sqlite3.Row
    return c


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    pdf_module.PDF_ROOT = _pdf_root
    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    for p in (_PATH, _PATH_NOVO):
        c.execute(
            "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, 1, ?)",
            (p, now),
        )
    c.commit()
    c.close()
    yield


def test_resumo_pdf_sem_progresso_defaults():
    # PDF com dono mas sem progresso nem material → tem_retomada False, contagens 0.
    r = client.get(f"/api/progress-resumo/{_PATH_NOVO}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["current_page"] == 1
    assert d["progresso_pct"] == 0
    assert d["n_notas"] == 0 and d["n_bookmarks"] == 0
    assert d["n_destaques"] == 0 and d["n_revisao"] == 0
    assert d["tem_retomada"] is False


def test_resumo_com_progresso_e_contagens():
    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    # Progresso: página 30 de 100.
    c.execute(
        "INSERT OR REPLACE INTO progress (path, current_page, total_pages, user_id, last_read_at) VALUES (?, 30, 100, 1, ?)",
        (_PATH, now),
    )
    # Material do usuário 1 neste PDF.
    c.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, 5, 'nota', ?, 1)", (_PATH, now))
    c.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, 6, 'nota2', ?, 1)", (_PATH, now))
    c.execute("INSERT INTO bookmarks_pdf (pdf_path, pagina, label, cor, created_at, user_id) VALUES (?, 10, 'L', 'blue', ?, 1)", (_PATH, now))
    c.execute("INSERT INTO destaques_pdf (user_id, pdf_path, pagina, cor, texto, rects, created_at) VALUES (1, ?, 12, 'yellow', 't', '[]', ?)", (_PATH, now))
    c.execute("INSERT INTO revisao_blocos (user_id, pdf_path, tipo, titulo, conteudo, pagina, ordem, created_at) VALUES (1, ?, 'texto', 'T', 'c', 12, 0, ?)", (_PATH, now))
    c.commit()
    c.close()

    r = client.get(f"/api/progress-resumo/{_PATH}")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["current_page"] == 30
    assert d["total_pages"] == 100
    assert d["progresso_pct"] == 30
    assert d["last_read_at"] != ""
    assert d["n_notas"] == 2
    assert d["n_bookmarks"] == 1
    assert d["n_destaques"] == 1
    assert d["n_revisao"] == 1
    assert d["tem_retomada"] is True


def test_resumo_contagens_isoladas_por_usuario():
    # Notas de OUTRO usuário (id 999) não devem contar para o user 1.
    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    c.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, 1, 'de outro', ?, 999)", (_PATH_NOVO, now))
    c.commit()
    c.close()
    d = client.get(f"/api/progress-resumo/{_PATH_NOVO}").json()
    assert d["n_notas"] == 0  # a nota é do user 999, não do 1


def test_resumo_caminho_invalido():
    r = client.get("/api/progress-resumo/../etc/passwd")
    # Traversal: rota rejeita (404) ou o handler barra (400).
    assert r.status_code in (400, 404)

"""Testes de GET /api/engajamento/{path} — heatmap de engajamento por página.

Agrega notas/bookmarks/destaques/blocos de revisão do usuário POR PÁGINA, com
score ponderado. Base isolada (TEST_DB), AUTH_ENABLED=false → user 1. PDF com
dono registrado (fail-closed).
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_engaj.db", delete=False)
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

_pdf_root = tempfile.mkdtemp(prefix="pdfroot_engaj_")
Path(_pdf_root, "Materia").mkdir(parents=True, exist_ok=True)
Path(_pdf_root, "Materia", "aula.pdf").write_bytes(b"%PDF-1.4 fake")
Path(_pdf_root, "Materia", "vazio.pdf").write_bytes(b"%PDF-1.4 fake")

_PATH = "Materia/aula.pdf"
_PATH_VAZIO = "Materia/vazio.pdf"


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
    for p in (_PATH, _PATH_VAZIO):
        c.execute(
            "INSERT OR REPLACE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, 1, ?)",
            (p, now),
        )
    c.commit()
    c.close()
    yield


def test_engajamento_vazio():
    d = client.get(f"/api/engajamento/{_PATH_VAZIO}").json()
    assert d["paginas"] == []
    assert d["max_score"] == 0
    assert d["total_paginas_com_atividade"] == 0


def test_engajamento_agrega_por_pagina():
    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    c.execute("INSERT OR REPLACE INTO progress (path, current_page, total_pages, user_id, last_read_at) VALUES (?, 1, 50, 1, ?)", (_PATH, now))
    # Página 5: 2 notas + 1 destaque → score 2*2 + 1 = 5
    c.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, 5, 'n1', ?, 1)", (_PATH, now))
    c.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, 5, 'n2', ?, 1)", (_PATH, now))
    c.execute("INSERT INTO destaques_pdf (user_id, pdf_path, pagina, cor, texto, rects, created_at) VALUES (1, ?, 5, 'yellow', 't', '[]', ?)", (_PATH, now))
    # Página 12: 1 bookmark + 1 bloco de revisão → score 1 + 2 = 3
    c.execute("INSERT INTO bookmarks_pdf (pdf_path, pagina, label, cor, created_at, user_id) VALUES (?, 12, 'L', 'blue', ?, 1)", (_PATH, now))
    c.execute("INSERT INTO revisao_blocos (user_id, pdf_path, tipo, titulo, conteudo, pagina, ordem, created_at) VALUES (1, ?, 'texto', 'T', 'c', 12, 0, ?)", (_PATH, now))
    c.commit()
    c.close()

    d = client.get(f"/api/engajamento/{_PATH}").json()
    assert d["total_pages"] == 50
    assert d["total_paginas_com_atividade"] == 2
    por_pag = {p["pagina"]: p for p in d["paginas"]}
    assert por_pag[5]["notas"] == 2 and por_pag[5]["destaques"] == 1
    assert por_pag[5]["score"] == 5
    assert por_pag[12]["bookmarks"] == 1 and por_pag[12]["revisao"] == 1
    assert por_pag[12]["score"] == 3
    assert d["max_score"] == 5
    # Ordenado por página crescente.
    assert [p["pagina"] for p in d["paginas"]] == [5, 12]


def test_engajamento_isolado_por_usuario():
    now = datetime.now(timezone.utc).isoformat()
    c = _conn()
    # Nota de outro usuário no _PATH_VAZIO não deve contar para user 1.
    c.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at, user_id) VALUES (?, 3, 'de outro', ?, 999)", (_PATH_VAZIO, now))
    c.commit()
    c.close()
    d = client.get(f"/api/engajamento/{_PATH_VAZIO}").json()
    assert d["paginas"] == []


def test_engajamento_caminho_invalido():
    r = client.get("/api/engajamento/../etc/passwd")
    assert r.status_code in (400, 404)

"""Testes da camada de destaques (marca-texto) por página — routers/destaques.py.

Cobre: CRUD, isolamento por user_id, validação de cor/rects (clamp, JSON).
"""
import json
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_destaques.db", delete=False)
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

PDF_PATH = "Informática/Redes.pdf"
RECTS = '[{"x":0.1,"y":0.2,"w":0.5,"h":0.03}]'


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


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute("DELETE FROM destaques_pdf")
    conn.commit()
    conn.close()
    yield


def test_criar_e_listar_destaque():
    r = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 3, "cor": "yellow", "texto": "TCP/IP", "rects": RECTS,
    })
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    lst = client.get(f"/api/destaques/{PDF_PATH}").json()
    assert len(lst) == 1
    d = lst[0]
    assert d["pagina"] == 3 and d["cor"] == "yellow" and d["texto"] == "TCP/IP"
    regs = json.loads(d["rects"])
    assert regs[0]["x"] == 0.1 and regs[0]["w"] == 0.5


def test_cor_invalida_422():
    r = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "chartreuse", "rects": RECTS,
    })
    assert r.status_code == 422


def test_rects_invalido_422():
    r = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "green", "rects": "não é json",
    })
    assert r.status_code == 422


def test_rects_sem_retangulo_valido_422():
    # área zero -> descartado -> nenhum válido -> 422
    r = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "green", "rects": '[{"x":0.1,"y":0.1,"w":0,"h":0.1}]',
    })
    assert r.status_code == 422


def test_rects_clamp():
    r = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "blue",
        "rects": '[{"x":-0.5,"y":0.2,"w":2.0,"h":0.05}]',
    })
    assert r.status_code == 200
    regs = json.loads(client.get(f"/api/destaques/{PDF_PATH}").json()[0]["rects"])
    assert regs[0]["x"] == 0.0 and regs[0]["w"] == 1.0


def test_excluir_destaque():
    rid = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 2, "cor": "pink", "rects": RECTS,
    }).json()["id"]
    d = client.delete(f"/api/destaques/{rid}")
    assert d.status_code == 200
    assert len(client.get(f"/api/destaques/{PDF_PATH}").json()) == 0


def test_isolamento_por_usuario():
    # Cria um destaque de outro usuário direto no banco.
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute(
        "INSERT INTO destaques_pdf (user_id, pdf_path, pagina, cor, texto, rects, created_at) VALUES (99, ?, 1, 'yellow', 'x', ?, '2020-01-01')",
        (PDF_PATH, RECTS),
    )
    conn.commit()
    conn.close()
    # O usuário padrão (1) não vê o destaque do 99.
    assert len(client.get(f"/api/destaques/{PDF_PATH}").json()) == 0


def test_path_traversal_bloqueado():
    r = client.get("/api/destaques/../../etc/passwd")
    assert r.status_code in (400, 404)


def test_estilo_default_highlight():
    client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "yellow", "rects": RECTS,
    })
    d = client.get(f"/api/destaques/{PDF_PATH}").json()[0]
    assert d["estilo"] == "highlight"


def test_estilos_validos():
    for estilo in ("highlight", "underline", "strike", "box"):
        r = client.post("/api/destaques", json={
            "pdf_path": PDF_PATH, "pagina": 1, "cor": "green", "rects": RECTS, "estilo": estilo,
        })
        assert r.status_code == 200, r.text
        assert r.json()["estilo"] == estilo


def test_estilo_invalido_422():
    r = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "green", "rects": RECTS, "estilo": "neon",
    })
    assert r.status_code == 422


def test_criar_com_comentario():
    client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "yellow", "rects": RECTS, "comentario": "cai muito em prova",
    })
    d = client.get(f"/api/destaques/{PDF_PATH}").json()[0]
    assert d["comentario"] == "cai muito em prova"


def test_editar_comentario_e_cor_via_put():
    rid = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "yellow", "rects": RECTS,
    }).json()["id"]
    r = client.put(f"/api/destaques/{rid}", json={"comentario": "revisar depois", "cor": "pink"})
    assert r.status_code == 200
    d = client.get(f"/api/destaques/{PDF_PATH}").json()[0]
    assert d["comentario"] == "revisar depois" and d["cor"] == "pink"


def test_put_destaque_inexistente_404():
    r = client.put("/api/destaques/999999", json={"comentario": "x"})
    assert r.status_code == 404


def test_put_cor_invalida_422():
    rid = client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 1, "cor": "yellow", "rects": RECTS,
    }).json()["id"]
    r = client.put(f"/api/destaques/{rid}", json={"cor": "roxo-neon"})
    assert r.status_code == 422


def test_export_markdown():
    client.post("/api/destaques", json={
        "pdf_path": PDF_PATH, "pagina": 2, "cor": "green", "texto": "Firewall filtra tráfego",
        "rects": RECTS, "estilo": "underline", "comentario": "cai em prova",
    })
    r = client.get(f"/api/destaques/{PDF_PATH}/export")
    assert r.status_code == 200, r.text
    assert "text/markdown" in r.headers.get("content-type", "")
    assert "attachment" in r.headers.get("content-disposition", "")
    md = r.text
    assert "# Destaques" in md
    assert "## Página 2" in md
    assert "Firewall filtra tráfego" in md
    assert "green/sublinhado" in md
    assert "💬 cai em prova" in md


def test_export_vazio_nao_quebra():
    r = client.get("/api/destaques/PDF/Sem/Destaques.pdf/export")
    assert r.status_code == 200
    assert "Nenhum destaque" in r.text

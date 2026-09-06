"""Testes do Vade Mecum: parser de artigos + import de texto e de PDF."""
import io
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_vademecum.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app
from routers.vademecum import _parse_lei_texto


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _clean():
    app.dependency_overrides[get_db_session] = _override_db_session
    c = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    for tbl in ("vademecum_artigos", "vademecum_leis"):
        try:
            c.execute(f"DELETE FROM {tbl}")
        except Exception:
            pass
    c.commit()
    c.close()
    yield


TEXTO_EXEMPLO = """Art. 1º A República Federativa do Brasil constitui-se em Estado Democrático de Direito.
Parágrafo único. Todo o poder emana do povo.
I - a soberania;
II - a cidadania;
Art. 2º São Poderes da União, independentes e harmônicos entre si, o Legislativo, o Executivo e o Judiciário.
"""


# ============================================================
# PARSER PURO
# ============================================================

def test_parser_detecta_artigos_caput_paragrafo_inciso():
    artigos = _parse_lei_texto(TEXTO_EXEMPLO)
    assert len(artigos) == 2

    art1 = artigos[0]
    assert art1["numero"].startswith("Art. 1")
    assert "República Federativa" in art1["caput"]
    assert "Parágrafo único" in art1["paragrafos"]
    assert "I - a soberania" in art1["incisos"]
    assert "II - a cidadania" in art1["incisos"]
    # caput não deve conter os parágrafos/incisos
    assert "soberania" not in art1["caput"]

    assert artigos[1]["numero"].startswith("Art. 2")


def test_parser_texto_vazio():
    assert _parse_lei_texto("") == []
    assert _parse_lei_texto("texto sem artigos") == []


# ============================================================
# IMPORT DE TEXTO
# ============================================================

def _criar_lei(client, nome="Constituição Federal"):
    r = client.post("/api/vademecum/leis", json={"nome": nome, "sigla": "CF"})
    assert r.status_code == 200
    return r.json()["id"]


def test_importar_texto(client):
    lei_id = _criar_lei(client)
    r = client.post(f"/api/vademecum/leis/{lei_id}/importar-texto", json={"texto": TEXTO_EXEMPLO})
    assert r.status_code == 200
    assert r.json()["artigos_importados"] == 2

    artigos = client.get(f"/api/vademecum/leis/{lei_id}/artigos").json()
    assert len(artigos) == 2


# ============================================================
# IMPORT DE PDF
# ============================================================

def _gerar_pdf_bytes(texto: str) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    for linha in texto.split("\n"):
        c.drawString(40, y, linha)
        y -= 16
    c.save()
    buf.seek(0)
    return buf.read()


def test_importar_pdf(client):
    lei_id = _criar_lei(client)
    pdf_bytes = _gerar_pdf_bytes(TEXTO_EXEMPLO)
    r = client.post(
        f"/api/vademecum/leis/{lei_id}/importar-pdf",
        files={"file": ("lei.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 200
    # O parser deve detectar os 2 artigos a partir do texto extraído do PDF
    assert r.json()["artigos_importados"] == 2


def test_importar_pdf_lei_inexistente(client):
    pdf_bytes = _gerar_pdf_bytes(TEXTO_EXEMPLO)
    r = client.post(
        "/api/vademecum/leis/99999/importar-pdf",
        files={"file": ("lei.pdf", pdf_bytes, "application/pdf")},
    )
    assert r.status_code == 404


def test_importar_pdf_rejeita_nao_pdf(client):
    lei_id = _criar_lei(client)
    r = client.post(
        f"/api/vademecum/leis/{lei_id}/importar-pdf",
        files={"file": ("lei.txt", b"conteudo", "text/plain")},
    )
    assert r.status_code == 400


# ============================================================
# GET /artigos/{id} — artigo único (elimina N+1 no frontend)
# ============================================================

def test_obter_artigo_por_id_inclui_lei_nome(client):
    lei_id = _criar_lei(client, nome="Constituição Federal")
    client.post(f"/api/vademecum/leis/{lei_id}/importar-texto", json={"texto": TEXTO_EXEMPLO})
    artigos = client.get(f"/api/vademecum/leis/{lei_id}/artigos").json()
    assert len(artigos) >= 1
    art_id = artigos[0]["id"]

    r = client.get(f"/api/vademecum/artigos/{art_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == art_id
    # JOIN traz o nome/sigla da lei para o frontend exibir sem varrer todas as leis.
    assert data["lei_nome"] == "Constituição Federal"
    assert data["lei_sigla"] == "CF"
    assert "República Federativa" in data["caput"]


def test_obter_artigo_inexistente_404(client):
    r = client.get("/api/vademecum/artigos/999999")
    assert r.status_code == 404

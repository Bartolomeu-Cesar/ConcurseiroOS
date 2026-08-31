"""Testes do endpoint POST /api/revisao-ia/gerar (auto-gerar blocos de revisão).

LLM mockado (patch em routers.ai_tutor.call_llm_sync). Gera um PDF real
(reportlab) num PDF_ROOT temporário para exercitar a extração de texto.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_revisao_ia.db", delete=False)
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
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)

_pdf_root = tempfile.mkdtemp(prefix="pdfroot_revia_")
_PDF_REL = "Informática/Redes.pdf"


def _gerar_pdf_teste(path: Path):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4)
    paginas = [
        "Pagina 1: Uma rede de computadores conecta dispositivos para compartilhar recursos. "
        "O protocolo TCP/IP e a base da comunicacao na internet, dividido em camadas.",
        "Pagina 2: O modelo OSI possui sete camadas: fisica, enlace, rede, transporte, sessao, "
        "apresentacao e aplicacao. Cada camada tem responsabilidades bem definidas.",
    ]
    for texto in paginas:
        y = 800
        for chunk in [texto[i:i + 90] for i in range(0, len(texto), 90)]:
            c.drawString(50, y, chunk)
            y -= 20
        c.showPage()
    c.save()


@pytest.fixture(scope="module", autouse=True)
def _setup_pdf_root():
    _gerar_pdf_teste(Path(_pdf_root) / _PDF_REL)
    old_root = pdf_module.PDF_ROOT
    pdf_module.PDF_ROOT = _pdf_root
    yield
    pdf_module.PDF_ROOT = old_root


@pytest.fixture(autouse=True)
def _ensure_state():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    pdf_module.PDF_ROOT = _pdf_root
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute("DELETE FROM revisao_blocos")
    conn.commit()
    conn.close()
    yield


@patch("routers.ai_tutor.call_llm_sync")
def test_gerar_revisao_ia_salva_blocos(mock_llm):
    mock_llm.return_value = (
        '[{"titulo":"TCP/IP","conteudo":"Base da internet, dividido em camadas."},'
        '{"titulo":"Modelo OSI","conteudo":"Sete camadas, da fisica a aplicacao."}]',
        200,
    )
    r = client.post("/api/revisao-ia/gerar", json={
        "pdf_path": _PDF_REL, "pagina_inicial": 1, "pagina_final": 2, "materia": "Informática",
    })
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["salvos"] == 2

    blocos = client.get(f"/api/revisao/{_PDF_REL}").json()
    assert len(blocos) == 2
    assert all(b["tipo"] == "resumo_ia" for b in blocos)
    titulos = {b["titulo"] for b in blocos}
    assert "TCP/IP" in titulos and "Modelo OSI" in titulos


@patch("routers.ai_tutor.call_llm_sync")
def test_gerar_revisao_ia_ignora_blocos_sem_conteudo(mock_llm):
    mock_llm.return_value = (
        '[{"titulo":"Vazio","conteudo":""},{"titulo":"Válido","conteudo":"Conteúdo ok."}]',
        100,
    )
    r = client.post("/api/revisao-ia/gerar", json={"pdf_path": _PDF_REL, "pagina_inicial": 1})
    assert r.status_code == 200
    assert r.json()["salvos"] == 1


@patch("routers.ai_tutor.call_llm_sync")
def test_gerar_revisao_ia_json_invalido_422(mock_llm):
    mock_llm.return_value = ("não é json", 50)
    r = client.post("/api/revisao-ia/gerar", json={"pdf_path": _PDF_REL, "pagina_inicial": 1})
    assert r.status_code == 422


def test_gerar_revisao_ia_path_traversal_bloqueado():
    r = client.post("/api/revisao-ia/gerar", json={"pdf_path": "../../etc/passwd", "pagina_inicial": 1})
    assert r.status_code == 400


@patch("routers.ai_tutor.call_llm_sync")
def test_gerar_revisao_ia_pagina_final_menor_422(mock_llm):
    mock_llm.return_value = ("[]", 10)
    r = client.post("/api/revisao-ia/gerar", json={
        "pdf_path": _PDF_REL, "pagina_inicial": 5, "pagina_final": 2,
    })
    assert r.status_code == 422

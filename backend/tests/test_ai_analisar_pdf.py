"""Testes do endpoint POST /api/ai/analisar-pdf (IA analisa trecho de PDF).

Fase 1a: ação 'resumo'. LLM mockado (patch em routers.ai_tutor.call_llm_sync).
Gera um PDF real (reportlab) num PDF_ROOT temporário para exercitar a extração
por intervalo de páginas e a proteção anti-traversal.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_analisar_pdf.db", delete=False)
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

# PDF_ROOT temporário com um PDF de teste real (3 páginas de teoria).
_pdf_root = tempfile.mkdtemp(prefix="pdfroot_")
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
        "Pagina 3: O firewall filtra o trafego de rede segundo regras de seguranca. "
        "O protocolo HTTPS usa TLS para cifrar a comunicacao entre cliente e servidor.",
    ]
    for texto in paginas:
        # quebra o texto em linhas para caber
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
    """Reafirma o override de DB e o PDF_ROOT antes de cada teste.

    Outros módulos de teste compartilham o mesmo `app` e podem sobrescrever o
    dependency_override de get_db_session ou o PDF_ROOT global. Reafirmar aqui
    garante isolamento na suíte completa.
    """
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    pdf_module.PDF_ROOT = _pdf_root
    yield


class TestAnalisarPdfResumo:
    @patch("routers.ai_tutor.call_llm_sync")
    def test_resumo_sucesso(self, mock_llm):
        mock_llm.return_value = ("## Resumo\nRedes conectam dispositivos.\n> Macete: OSI = 7 camadas.", 120)
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL,
            "acao": "resumo",
            "pagina_inicial": 1,
            "pagina_final": 3,
            "materia": "Informática",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["ok"] is True
        assert data["acao"] == "resumo"
        assert "Resumo" in data["resumo"]
        assert data["tokens_usados"] == 120
        assert data["paginas"]["total"] == 3
        # O LLM recebeu o texto extraído do trecho
        args, kwargs = mock_llm.call_args
        messages = args[0]
        prompt_usuario = messages[-1]["content"]
        assert "TCP/IP" in prompt_usuario or "rede" in prompt_usuario.lower()

    @patch("routers.ai_tutor.call_llm_sync")
    def test_resumo_intervalo_pagina_unica(self, mock_llm):
        mock_llm.return_value = ("## Resumo\nModelo OSI.", 80)
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "resumo", "pagina_inicial": 2, "pagina_final": 2,
        })
        assert r.status_code == 200
        # Só a página 2 deve ter sido enviada
        prompt = mock_llm.call_args[0][0][-1]["content"]
        assert "OSI" in prompt
        assert "firewall" not in prompt.lower()  # página 3 não incluída

    def test_pdf_inexistente_404(self):
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": "Informática/NaoExiste.pdf", "acao": "resumo",
        })
        assert r.status_code == 404

    def test_path_traversal_bloqueado(self):
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": "../../etc/passwd", "acao": "resumo",
        })
        assert r.status_code == 400

    def test_acao_invalida_422(self):
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "traduzir",
        })
        assert r.status_code == 422

    def test_pagina_final_menor_que_inicial_422(self):
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "resumo", "pagina_inicial": 3, "pagina_final": 1,
        })
        assert r.status_code == 422


class TestAnalisarPdfFlashcards:
    @patch("routers.ai_tutor.call_llm_sync")
    def test_flashcards_gera_e_parseia(self, mock_llm):
        mock_llm.return_value = (
            '[{"pergunta": "O que é TCP/IP?", "resposta": "Base da comunicação na internet."},'
            ' {"pergunta": "Quantas camadas tem o OSI?", "resposta": "Sete."}]',
            200,
        )
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "flashcards", "pagina_inicial": 1, "pagina_final": 3,
            "quantidade": 2, "materia": "Informática",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["acao"] == "flashcards"
        assert isinstance(data["flashcards"], list)
        assert len(data["flashcards"]) == 2
        assert data["salvo"] is False  # salvar não pedido
        assert data["salvos"] == 0

    @patch("routers.ai_tutor.call_llm_sync")
    def test_flashcards_salva_no_banco(self, mock_llm):
        mock_llm.return_value = (
            '```json\n[{"pergunta": "P1", "resposta": "R1"}, {"pergunta": "P2", "resposta": "R2"}]\n```',
            150,
        )
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "flashcards", "materia": "Redes", "salvar": True,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["salvo"] is True
        assert data["salvos"] == 2
        # confirma persistência
        c = sqlite3.connect(_tmp_db.name, timeout=10)
        try:
            n = c.execute(
                "SELECT COUNT(*) FROM flashcards WHERE materia = 'Redes' AND pergunta IN ('P1','P2')"
            ).fetchone()[0]
        finally:
            c.close()
        assert n == 2

    @patch("routers.ai_tutor.call_llm_sync")
    def test_flashcards_json_invalido_nao_quebra(self, mock_llm):
        mock_llm.return_value = ("desculpe, não consegui gerar", 50)
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "flashcards", "salvar": True,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["flashcards"] is None
        assert data["salvos"] == 0
        assert data["salvo"] is False


class TestAnalisarPdfQuestoes:
    _JSON_Q = (
        '[{"enunciado": "O protocolo HTTPS usa qual tecnologia para cifrar?",'
        ' "alternativa_a": "TLS", "alternativa_b": "FTP", "alternativa_c": "SMTP",'
        ' "alternativa_d": "DNS", "alternativa_e": "ARP", "resposta_correta": "A",'
        ' "explicacao": "HTTPS = HTTP sobre TLS."},'
        ' {"enunciado": "Quantas camadas tem o modelo OSI?",'
        ' "alternativa_a": "4", "alternativa_b": "5", "alternativa_c": "6",'
        ' "alternativa_d": "7", "alternativa_e": "8", "resposta_correta": "D",'
        ' "explicacao": "O modelo OSI tem 7 camadas."}]'
    )

    @patch("routers.ai_tutor.call_llm_sync")
    def test_questoes_gera_e_parseia(self, mock_llm):
        mock_llm.return_value = (self._JSON_Q, 300)
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "questoes", "pagina_inicial": 1, "pagina_final": 3,
            "quantidade": 2, "materia": "Informática",
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["acao"] == "questoes"
        assert isinstance(data["questoes"], list)
        assert len(data["questoes"]) == 2
        assert data["salvo"] is False

    @patch("routers.ai_tutor.call_llm_sync")
    def test_questoes_salva_no_banco_com_prova_origem(self, mock_llm):
        mock_llm.return_value = (self._JSON_Q, 300)
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "questoes", "materia": "Informática", "salvar": True,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["salvo"] is True
        assert data["salvos"] == 2
        c = sqlite3.connect(_tmp_db.name, timeout=10)
        try:
            rows = c.execute(
                "SELECT materia, resposta_correta, prova_origem, banca FROM questoes "
                "WHERE prova_origem = 'IA: Redes' ORDER BY id"
            ).fetchall()
        finally:
            c.close()
        assert len(rows) == 2
        assert rows[0][0] == "Informática"      # materia
        assert rows[0][1] in ("A", "D")          # resposta_correta preenchida
        assert rows[0][3] == "IA"                # banca

    @patch("routers.ai_tutor.call_llm_sync")
    def test_questoes_json_invalido_nao_quebra(self, mock_llm):
        mock_llm.return_value = ("não foi possível", 40)
        r = client.post("/api/ai/analisar-pdf", json={
            "pdf_path": _PDF_REL, "acao": "questoes", "salvar": True,
        })
        assert r.status_code == 200
        data = r.json()
        assert data["questoes"] is None
        assert data["salvos"] == 0

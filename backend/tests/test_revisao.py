"""Testes do Caderno de Revisão por PDF (routers/revisao.py).

Cobre: CRUD de blocos, isolamento por user_id, validações (tipo, imagem,
data URI), ordenação automática e export Markdown.
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_revisao.db", delete=False)
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

# Imagem PNG 1x1 transparente como data URI (recorte mínimo válido).
PNG_1X1 = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)
PDF_PATH = "Informática/Redes.pdf"


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
def _ensure_db_revisao():
    """Garante que o DB correto está ativo antes de cada teste (isolamento
    cross-module: outros módulos de teste sobrescrevem o override global)."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield



def _limpar():
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute("DELETE FROM revisao_blocos")
    conn.commit()
    conn.close()


def test_criar_recorte_e_listar():
    _limpar()
    r = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte",
        "titulo": "Topologias", "imagem_data": PNG_1X1, "pagina": 3,
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["ordem"] == 0

    r2 = client.get(f"/api/revisao/{PDF_PATH}")
    assert r2.status_code == 200
    blocos = r2.json()
    assert len(blocos) == 1
    assert blocos[0]["tipo"] == "recorte"
    assert blocos[0]["titulo"] == "Topologias"
    assert blocos[0]["pagina"] == 3
    assert blocos[0]["imagem_data"].startswith("data:image/png")


def test_ordem_incrementa():
    _limpar()
    client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "recorte", "imagem_data": PNG_1X1, "pagina": 1})
    r = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "texto", "conteudo": "Segundo bloco", "pagina": 2})
    assert r.json()["ordem"] == 1


def test_recorte_sem_imagem_falha():
    _limpar()
    r = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "recorte", "pagina": 1})
    assert r.status_code == 422


def test_texto_sem_conteudo_falha():
    _limpar()
    r = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "texto", "pagina": 1})
    assert r.status_code == 422


def test_tipo_invalido_falha():
    _limpar()
    r = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "xpto", "conteudo": "x", "pagina": 1})
    assert r.status_code == 422


def test_imagem_data_uri_invalido_falha():
    _limpar()
    r = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte",
        "imagem_data": "javascript:alert(1)", "pagina": 1,
    })
    assert r.status_code == 422


def test_path_traversal_bloqueado():
    _limpar()
    r = client.post("/api/revisao", json={"pdf_path": "../etc/passwd", "tipo": "texto", "conteudo": "x", "pagina": 1})
    assert r.status_code == 400


def test_editar_bloco():
    _limpar()
    rid = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "texto", "conteudo": "orig", "pagina": 1}).json()["id"]
    r = client.put(f"/api/revisao/{rid}", json={"titulo": "Novo título", "conteudo": "editado"})
    assert r.status_code == 200
    blocos = client.get(f"/api/revisao/{PDF_PATH}").json()
    assert blocos[0]["titulo"] == "Novo título"
    assert blocos[0]["conteudo"] == "editado"


def test_reordenar_bloco():
    _limpar()
    id1 = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "texto", "conteudo": "A", "pagina": 1}).json()["id"]
    id2 = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "texto", "conteudo": "B", "pagina": 2}).json()["id"]
    # Move B para o topo
    client.put(f"/api/revisao/{id2}", json={"ordem": -1})
    blocos = client.get(f"/api/revisao/{PDF_PATH}").json()
    assert blocos[0]["conteudo"] == "B"
    assert blocos[1]["conteudo"] == "A"
    assert {b["id"] for b in blocos} == {id1, id2}


def test_editar_inexistente_404():
    _limpar()
    r = client.put("/api/revisao/999999", json={"titulo": "x"})
    assert r.status_code == 404


def test_excluir_bloco():
    _limpar()
    rid = client.post("/api/revisao", json={"pdf_path": PDF_PATH, "tipo": "texto", "conteudo": "del", "pagina": 1}).json()["id"]
    r = client.delete(f"/api/revisao/{rid}")
    assert r.status_code == 200
    assert client.get(f"/api/revisao/{PDF_PATH}").json() == []


def test_export_markdown():
    _limpar()
    client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte",
        "titulo": "Camadas OSI", "imagem_data": PNG_1X1, "pagina": 5,
    })
    client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "resumo_ia",
        "titulo": "Resumo", "conteudo": "As 7 camadas do modelo OSI...", "pagina": 5,
    })
    r = client.get(f"/api/revisao/{PDF_PATH}/export")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert "attachment" in r.headers["content-disposition"]
    md = r.text
    assert "# Caderno de Revisão — Redes" in md
    assert "## Camadas OSI" in md
    assert "![Recorte p.5](data:image/png" in md
    assert "As 7 camadas do modelo OSI..." in md
    assert "_Página 5_" in md


def test_isolamento_por_user():
    """Blocos de um user não aparecem/são editáveis por outro user."""
    _limpar()
    # Insere bloco direto como user_id=42
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute(
        """INSERT INTO revisao_blocos (user_id, pdf_path, tipo, titulo, conteudo, imagem_data, pagina, ordem, created_at)
           VALUES (42, ?, 'texto', 'do outro', 'segredo', '', 1, 0, '2026-01-01T00:00:00')""",
        (PDF_PATH,),
    )
    conn.commit()
    outro_id = conn.execute("SELECT id FROM revisao_blocos WHERE user_id = 42").fetchone()[0]
    conn.close()

    # user default (1) não vê o bloco do user 42
    blocos = client.get(f"/api/revisao/{PDF_PATH}").json()
    assert all(b["titulo"] != "do outro" for b in blocos)

    # Não consegue editar bloco de outro user
    r = client.put(f"/api/revisao/{outro_id}", json={"titulo": "hack"})
    assert r.status_code == 404

    # Delete não afeta bloco de outro user
    client.delete(f"/api/revisao/{outro_id}")
    conn = sqlite3.connect(_tmp_db.name)
    ainda = conn.execute("SELECT COUNT(*) FROM revisao_blocos WHERE id = ?", (outro_id,)).fetchone()[0]
    conn.close()
    assert ainda == 1


def _contar_flashcards(pergunta_like=None):
    conn = sqlite3.connect(_tmp_db.name)
    if pergunta_like:
        n = conn.execute("SELECT COUNT(*) FROM flashcards WHERE pergunta = ?", (pergunta_like,)).fetchone()[0]
    else:
        n = conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0]
    conn.close()
    return n


def test_bloco_texto_para_flashcard():
    _limpar()
    rid = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "texto",
        "titulo": "O que é uma LAN?", "conteudo": "Rede local que conecta dispositivos próximos.", "pagina": 2,
    }).json()["id"]
    r = client.post(f"/api/revisao/{rid}/flashcard")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["ok"] is True
    assert data["pergunta"] == "O que é uma LAN?"
    assert data["materia"] == "Informática"  # derivado do 1º nível do pdf_path
    assert _contar_flashcards("O que é uma LAN?") == 1


def test_bloco_recorte_para_flashcard():
    _limpar()
    rid = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte",
        "titulo": "Topologia estrela", "imagem_data": PNG_1X1, "pagina": 7,
    }).json()["id"]
    r = client.post(f"/api/revisao/{rid}/flashcard")
    assert r.status_code == 200
    assert r.json()["pergunta"] == "Topologia estrela"


def test_bloco_recorte_sem_titulo_gera_pergunta_recall():
    _limpar()
    rid = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte", "imagem_data": PNG_1X1, "pagina": 9,
    }).json()["id"]
    r = client.post(f"/api/revisao/{rid}/flashcard")
    assert r.status_code == 200
    assert "página 9" in r.json()["pergunta"]


def test_flashcard_de_bloco_inexistente_404():
    _limpar()
    r = client.post("/api/revisao/999999/flashcard")
    assert r.status_code == 404


# ==================== Occlusão de imagem (image occlusion) ====================

def test_criar_recorte_com_oclusoes():
    _limpar()
    oclusoes = '[{"x":0.1,"y":0.2,"w":0.3,"h":0.05},{"x":0.5,"y":0.6,"w":0.2,"h":0.1}]'
    r = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte",
        "titulo": "Tabela", "imagem_data": PNG_1X1, "pagina": 4, "oclusoes": oclusoes,
    })
    assert r.status_code == 200, r.text
    blocos = client.get(f"/api/revisao/{PDF_PATH}").json()
    import json
    regs = json.loads(blocos[0]["oclusoes"])
    assert len(regs) == 2
    assert regs[0]["x"] == 0.1 and regs[0]["w"] == 0.3


def test_oclusoes_clampa_valores_fora_do_intervalo():
    _limpar()
    # x negativo e w > 1 devem ser clampados para [0,1]; retângulos sem área somem.
    oclusoes = '[{"x":-0.5,"y":0.2,"w":2.0,"h":0.1},{"x":0.1,"y":0.1,"w":0,"h":0.1}]'
    r = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte", "imagem_data": PNG_1X1, "pagina": 1, "oclusoes": oclusoes,
    })
    assert r.status_code == 200
    import json
    regs = json.loads(client.get(f"/api/revisao/{PDF_PATH}").json()[0]["oclusoes"])
    assert len(regs) == 1  # o de área zero foi descartado
    assert regs[0]["x"] == 0.0 and regs[0]["w"] == 1.0


def test_oclusoes_json_invalido_422():
    _limpar()
    r = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte", "imagem_data": PNG_1X1, "pagina": 1,
        "oclusoes": "não é json",
    })
    assert r.status_code == 422


def test_atualizar_oclusoes_via_put():
    _limpar()
    rid = client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "recorte", "imagem_data": PNG_1X1, "pagina": 1,
    }).json()["id"]
    # Sem oclusões inicialmente
    assert client.get(f"/api/revisao/{PDF_PATH}").json()[0]["oclusoes"] == ""
    # Adiciona via PUT
    r = client.put(f"/api/revisao/{rid}", json={"oclusoes": '[{"x":0.2,"y":0.2,"w":0.1,"h":0.1}]'})
    assert r.status_code == 200
    import json
    regs = json.loads(client.get(f"/api/revisao/{PDF_PATH}").json()[0]["oclusoes"])
    assert len(regs) == 1


def test_bloco_sem_oclusoes_retorna_string_vazia():
    _limpar()
    client.post("/api/revisao", json={
        "pdf_path": PDF_PATH, "tipo": "texto", "titulo": "T", "conteudo": "c", "pagina": 1,
    })
    assert client.get(f"/api/revisao/{PDF_PATH}").json()[0]["oclusoes"] == ""

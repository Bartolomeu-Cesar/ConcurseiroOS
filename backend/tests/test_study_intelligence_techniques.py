"""Testes dos caminhos de erro de study_intelligence/techniques.py.

Cobre os ramos que antes quebravam por HTTPException indefinido (F821) — hoje
corrigidos com o import de módulo — e o endpoint sleep-consolidation, que tinha
uma definição duplicada (F811) removida:

- POST /api/study-intelligence/intention/{id}/concluir → 404 se a intenção não existe.
- GET  /api/study-intelligence/banca-training → 400 se a banca não existe.
- GET  /api/study-intelligence/sleep-consolidation → 200 (endpoint único, versão FSRS).

Estes eram os ramos que retornavam 500 (NameError) em vez do HTTP correto, por
falta do import de HTTPException no escopo. São caminhos de erro pouco trafegados,
por isso não eram cobertos — este teste fecha essa lacuna.

Executar: pytest tests/test_study_intelligence_techniques.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_tmp_db = tempfile.NamedTemporaryFile(suffix="_si_tech.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["TEST_DB"] = _tmp_db.name

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from deps import get_user_id
from fastapi.testclient import TestClient
from main import app

_UID = 1


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


async def _override_uid():
    return _UID


client = TestClient(app)


@pytest.fixture(autouse=True)
def _setup():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_user_id] = _override_uid
    yield
    app.dependency_overrides.pop(get_user_id, None)


# ==================== CAMINHO DE ERRO: INTENÇÃO 404 ====================


def test_concluir_intention_inexistente_retorna_404():
    # Antes da correção do import de HTTPException, este ramo estourava 500
    # (NameError) em vez de 404. Agora deve retornar 404 limpo.
    #
    # A tabela study_intentions é criada de forma lazy no POST de criação da
    # intenção; por isso registramos uma intenção primeiro (garante a tabela) e só
    # então tentamos concluir um id que não existe, atingindo o ramo do 404.
    criar = client.post(
        "/api/study-intelligence/intention",
        json={"materia": "Direito", "duracao_min": 25, "atividade": "questoes"},
    )
    assert criar.status_code in (200, 201)

    r = client.post("/api/study-intelligence/intention/999999/concluir", json={"reflexao": "x"})
    assert r.status_code == 404
    assert "não encontrada" in r.json()["detail"].lower()


# ==================== CAMINHO DE ERRO: BANCA 400 ====================


def test_banca_training_banca_inexistente_retorna_400():
    # Idem: ramo que estourava 500 por HTTPException indefinido. Agora 400.
    r = client.get("/api/study-intelligence/banca-training", params={"banca": "BANCA_QUE_NAO_EXISTE"})
    assert r.status_code == 400
    assert "não encontrada" in r.json()["detail"].lower()


def test_banca_training_banca_valida_nao_da_400():
    # Sanidade: uma banca conhecida NÃO cai no ramo de erro.
    r = client.get("/api/study-intelligence/banca-training", params={"banca": "CESPE"})
    assert r.status_code == 200


def test_banca_training_cebraspe_normaliza_para_cespe():
    # CEBRASPE é normalizado para CESPE (não deve dar 400).
    r = client.get("/api/study-intelligence/banca-training", params={"banca": "CEBRASPE"})
    assert r.status_code == 200


# ==================== SLEEP CONSOLIDATION (endpoint único após remover duplicata) ====================


def test_sleep_consolidation_responde_200():
    # Havia duas defs com a mesma rota (F811). Mantida a versão FSRS/Born & Wilhelm.
    r = client.get("/api/study-intelligence/sleep-consolidation")
    assert r.status_code == 200


def test_sleep_consolidation_tem_estrutura_esperada():
    # A versão mantida retorna o modo (noturno/matinal/fora_janela) conforme o horário.
    data = client.get("/api/study-intelligence/sleep-consolidation").json()
    assert isinstance(data, dict)
    # A versão FSRS expõe 'modo' — a versão antiga (removida) usava 'periodo'.
    assert "modo" in data


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

"""
Testes dos endpoints de importação do ConcurseiroOS.
Executar: pytest tests/test_imports.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_imports.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session
import settings as settings_mod

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app


def _override_db_session():
    """Override para garantir que FastAPI use o DB temporário deste módulo."""
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session


@pytest.fixture(scope="module")
def client():
    """TestClient compartilhado por todo o módulo de testes."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db_imports():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


class TestImports:
    def test_importar_edital_json(self, client):
        import json
        content = json.dumps([
            {"edital_nome": "Import Test", "cargo": "Analista", "materia": "Dir. Admin", "topico": "Atos administrativos"},
            {"edital_nome": "Import Test", "cargo": "Analista", "materia": "Dir. Admin", "topico": "Licitações"}
        ])
        r = client.post("/api/edital/importar", files={"file": ("edital.json", content, "application/json")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_edital_csv(self, client):
        csv_content = "edital_nome,cargo,materia,topico,status,horas_estudadas\nCSV Test,Tecnico,Portugues,Crase,Não Iniciado,0\n"
        r = client.post("/api/edital/importar", files={"file": ("edital.csv", csv_content, "text/csv")})
        assert r.status_code == 200
        assert r.json()["importados"] == 1

    def test_importar_ciclo_json(self, client):
        import json
        content = json.dumps([
            {"materia": "Matemática", "horas_alvo": 3.0},
            {"materia": "Português", "horas_alvo": 2.5}
        ])
        r = client.post("/api/ciclo/importar", files={"file": ("ciclo.json", content, "application/json")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_flashcards_json(self, client):
        import json
        content = json.dumps([
            {"pergunta": "O que é CPU?", "resposta": "Unidade Central de Processamento"},
            {"pergunta": "O que é RAM?", "resposta": "Memória de Acesso Aleatório"}
        ])
        r = client.post("/api/flashcards/importar", files={"file": ("flash.json", content, "application/json")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_flashcards_anki(self, client):
        anki_content = "O que é SSD?\tDisco de Estado Sólido\nO que é HDD?\tDisco Rígido\n"
        r = client.post("/api/flashcards/importar", files={"file": ("cards.txt", anki_content, "text/plain")})
        assert r.status_code == 200
        assert r.json()["importados"] == 2

    def test_importar_flashcards_csv(self, client):
        csv_content = "pergunta,resposta\nO que é GPU?,Unidade de Processamento Gráfico\n"
        r = client.post("/api/flashcards/importar", files={"file": ("flash.csv", csv_content, "text/csv")})
        assert r.status_code == 200
        assert r.json()["importados"] == 1

"""
Testes dos endpoints de exportação do ConcurseiroOS.
Executar: pytest tests/test_exports.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_exports.db", delete=False)
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
def _ensure_db_exports():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


@pytest.fixture(scope="module", autouse=True)
def _seed_data(client):
    """Seed data for export tests."""
    # Criar tópico de edital
    client.post("/api/edital", json={
        "edital_nome": "PC-MA 2026",
        "cargo": "Delegado",
        "materia": "Direito Penal",
        "topico": "Crimes contra a pessoa"
    })
    # Criar item no ciclo
    client.post("/api/ciclo", json={
        "materia": "Direito Constitucional",
        "horas_alvo": 3.0
    })
    # Criar flashcard
    client.post("/api/flashcards", json={
        "pergunta": "O que é mandado de segurança?",
        "resposta": "Remédio constitucional para proteger direito líquido e certo."
    })


class TestExports:
    def test_exportar_edital_json(self, client):
        r = client.get("/api/edital/exportar?formato=json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]
        assert "attachment" in r.headers.get("content-disposition", "")

    def test_exportar_edital_csv(self, client):
        r = client.get("/api/edital/exportar?formato=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]
        assert "edital_verticalizado.csv" in r.headers.get("content-disposition", "")

    def test_exportar_ciclo_json(self, client):
        r = client.get("/api/ciclo/exportar?formato=json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]

    def test_exportar_ciclo_csv(self, client):
        r = client.get("/api/ciclo/exportar?formato=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_exportar_flashcards_json(self, client):
        r = client.get("/api/flashcards/exportar?formato=json")
        assert r.status_code == 200
        assert "application/json" in r.headers["content-type"]

    def test_exportar_flashcards_csv(self, client):
        r = client.get("/api/flashcards/exportar?formato=csv")
        assert r.status_code == 200
        assert "text/csv" in r.headers["content-type"]

    def test_exportar_flashcards_anki(self, client):
        r = client.get("/api/flashcards/exportar?formato=anki")
        assert r.status_code == 200
        assert "tab-separated" in r.headers["content-type"]
        # Verificar que é TSV válido
        lines = r.text.strip().split("\n")
        if lines and lines[0]:  # se tem flashcards
            assert "\t" in lines[0]  # tab-separated

    def test_exportar_edital_filtrado(self, client):
        r = client.get("/api/edital/exportar?formato=json&edital_nome=PC-MA 2026")
        assert r.status_code == 200

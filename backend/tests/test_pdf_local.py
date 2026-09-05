"""
Testes do MODO PDF LOCAL (backend): persistência de progresso sob paths com
prefixo "local:".

No modo local, o binário do PDF fica na máquina do estudante (File System
Access API no frontend) e NUNCA é enviado ao servidor. O servidor só guarda o
progresso (página atual/total) via /api/progress, com o path prefixado por
"local:". Estes testes garantem que:

- o progresso de um path "local:" é salvo e lido normalmente;
- aparece no /api/progress-bulk;
- respeita o isolamento por usuário (PK path+user_id);
- paths com traversal ("..") continuam bloqueados;
- endpoints que tocam disco (serve_pdf / pdf-existe) não vazam nada para paths
  "local:" (retornam negado/404, pois o arquivo não existe no PDF_ROOT).

Executar: pytest tests/test_pdf_local.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_pdf_local.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from deps import get_user_id
from fastapi.testclient import TestClient
from main import app

LOCAL_PATH = "local:Direito/aula1.pdf"
LOCAL_PATH_2 = "local:aula_raiz.pdf"


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


def _override_user_id(uid):
    async def override():
        return uid
    return override


@pytest.fixture(autouse=True)
def _ensure():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    conn = sqlite3.connect(_tmp_db.name, timeout=10)
    conn.execute("DELETE FROM progress WHERE path LIKE 'local:%'")
    conn.commit()
    conn.close()
    yield
    app.dependency_overrides.pop(get_user_id, None)


# ==================== PROGRESSO LOCAL ====================

def test_salva_e_le_progresso_local():
    r = client.post(
        f"/api/progress/{LOCAL_PATH}",
        json={"current_page": 7, "total_pages": 20},
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    got = client.get(f"/api/progress/{LOCAL_PATH}").json()
    assert got["current_page"] == 7
    assert got["total_pages"] == 20


def test_progresso_local_aparece_no_bulk():
    client.post(f"/api/progress/{LOCAL_PATH}", json={"current_page": 3, "total_pages": 10})
    bulk = client.get("/api/progress-bulk").json()
    assert LOCAL_PATH in bulk
    assert bulk[LOCAL_PATH]["current_page"] == 3
    assert bulk[LOCAL_PATH]["total_pages"] == 10


def test_progresso_local_path_raiz():
    r = client.post(f"/api/progress/{LOCAL_PATH_2}", json={"current_page": 2, "total_pages": 5})
    assert r.status_code == 200
    got = client.get(f"/api/progress/{LOCAL_PATH_2}").json()
    assert got["current_page"] == 2


def test_progresso_local_isolado_por_usuario():
    # Usuário 10 grava.
    app.dependency_overrides[get_user_id] = _override_user_id(10)
    client.post(f"/api/progress/{LOCAL_PATH}", json={"current_page": 9, "total_pages": 30})
    # Usuário 20 não enxerga o progresso do 10.
    app.dependency_overrides[get_user_id] = _override_user_id(20)
    bulk = client.get("/api/progress-bulk").json()
    assert LOCAL_PATH not in bulk
    got = client.get(f"/api/progress/{LOCAL_PATH}").json()
    # Sem registro para o user 20 → default (page 1).
    assert got["current_page"] == 1


def test_progresso_local_bloqueia_traversal():
    # O frontend codifica cada segmento (encodeURIComponent); ".." codificado
    # chega literal ao handler, que deve rejeitar (400). Usamos %2E%2E para
    # evitar a normalização de path da URL pelo cliente de teste.
    r = client.post(
        "/api/progress/local:%2E%2E%2F%2E%2E%2Fetc%2Fpasswd",
        json={"current_page": 1, "total_pages": 1},
    )
    assert r.status_code == 400


# ==================== ENDPOINTS DE DISCO NÃO VAZAM ====================

def test_pdf_existe_falso_para_local():
    # O arquivo "local:" não existe no PDF_ROOT do servidor → existe=False.
    r = client.get(f"/api/pdf-existe/{LOCAL_PATH}")
    assert r.status_code == 200
    assert r.json()["existe"] is False


def test_serve_pdf_nao_serve_local():
    # /pdf/local:... não deve entregar arquivo (negado ou não encontrado).
    r = client.get(f"/pdf/{LOCAL_PATH}")
    assert r.status_code in (403, 404)

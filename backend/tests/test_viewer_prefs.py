"""Preferências do LEITOR de PDF persistidas em user_prefs (sincronizam entre estações).

GET  /api/config/viewer-prefs → {meta_paginas, meta_minutos, recall_intervalo}
PUT  /api/config/viewer-prefs → merge parcial + validação/limites

Cobre: defaults, persistência, merge parcial, clamp de limites, JSON inválido
tolerado, unicidade (PK user_id+chave) e isolamento por usuário.

Base isolada (TEST_DB). Executar: pytest tests/test_viewer_prefs.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_viewerprefs.db", delete=False)
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


def test_prefs_default(client):
    r = client.get("/api/config/viewer-prefs")
    assert r.status_code == 200
    d = r.json()
    assert d["meta_paginas"] == 0
    assert d["meta_minutos"] == 0
    assert d["recall_intervalo"] == 0


def test_definir_e_ler(client):
    r = client.put("/api/config/viewer-prefs", json={"meta_paginas": 20, "meta_minutos": 45, "recall_intervalo": 5})
    assert r.status_code == 200, r.text
    assert r.json()["meta_paginas"] == 20
    d = client.get("/api/config/viewer-prefs").json()
    assert d["meta_paginas"] == 20
    assert d["meta_minutos"] == 45
    assert d["recall_intervalo"] == 5


def test_merge_parcial_preserva_demais(client):
    client.put("/api/config/viewer-prefs", json={"meta_paginas": 10, "meta_minutos": 30, "recall_intervalo": 3})
    # Atualiza só recall_intervalo; os demais devem permanecer.
    r = client.put("/api/config/viewer-prefs", json={"recall_intervalo": 8})
    assert r.status_code == 200
    d = client.get("/api/config/viewer-prefs").json()
    assert d["meta_paginas"] == 10
    assert d["meta_minutos"] == 30
    assert d["recall_intervalo"] == 8


def test_clamp_limites(client):
    # Valores acima do teto e abaixo do piso são limitados.
    r = client.put("/api/config/viewer-prefs", json={"meta_paginas": 99999, "meta_minutos": -5, "recall_intervalo": 500})
    assert r.status_code == 200
    d = r.json()
    assert d["meta_paginas"] == 1000    # teto
    assert d["meta_minutos"] == 0       # piso
    assert d["recall_intervalo"] == 100  # teto


def test_unicidade_nao_duplica_linha(client):
    client.put("/api/config/viewer-prefs", json={"meta_paginas": 5})
    client.put("/api/config/viewer-prefs", json={"meta_paginas": 7})
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        n = c.execute("SELECT COUNT(*) FROM user_prefs WHERE chave='viewer_prefs'").fetchone()[0]
        assert n == 1
    finally:
        c.close()


def test_json_corrompido_tolerado(client):
    # Simula valor corrompido no banco → GET devolve defaults sem erro.
    # AUTH_ENABLED=false → a API usa DEFAULT_USER_ID = 1.
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute("DELETE FROM user_prefs WHERE user_id=1 AND chave='viewer_prefs'")
        c.execute(
            "INSERT INTO user_prefs (user_id, chave, valor, updated_at) VALUES (1, 'viewer_prefs', '{lixo', '2026-01-01')"
        )
        c.commit()
    finally:
        c.close()
    r = client.get("/api/config/viewer-prefs")
    assert r.status_code == 200
    d = r.json()
    assert d["meta_paginas"] == 0 and d["meta_minutos"] == 0 and d["recall_intervalo"] == 0


def test_isolamento_por_usuario(client):
    # Grava prefs para dois usuários distintos direto na tabela e confere que
    # não se misturam (a leitura via API usa DEFAULT_USER_ID = 1 sem auth).
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        c.execute(
            "INSERT INTO user_prefs (user_id, chave, valor, updated_at) VALUES (1, 'viewer_prefs', ?, '2026-01-01') "
            "ON CONFLICT(user_id, chave) DO UPDATE SET valor=excluded.valor",
            ('{"meta_paginas": 11, "meta_minutos": 0, "recall_intervalo": 0}',),
        )
        c.execute(
            "INSERT INTO user_prefs (user_id, chave, valor, updated_at) VALUES (999, 'viewer_prefs', ?, '2026-01-01') "
            "ON CONFLICT(user_id, chave) DO UPDATE SET valor=excluded.valor",
            ('{"meta_paginas": 77, "meta_minutos": 0, "recall_intervalo": 0}',),
        )
        c.commit()
        u999 = c.execute("SELECT valor FROM user_prefs WHERE user_id=999 AND chave='viewer_prefs'").fetchone()[0]
    finally:
        c.close()
    # A API (user 1) vê 11, não 77.
    d = client.get("/api/config/viewer-prefs").json()
    assert d["meta_paginas"] == 11
    # E o registro do outro usuário permanece intacto.
    assert '"meta_paginas": 77' in u999

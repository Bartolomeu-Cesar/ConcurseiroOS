"""Regressão: a CSP (Content-Security-Policy) deve permitir o embed do YouTube
no player de vídeo do edital. O frame-src era 'self' blob:, o que bloqueava o
iframe do YouTube (vídeo não carregava).

Executar: pytest tests/test_csp_youtube.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_csp.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _csp(client):
    r = client.get("/api/health")
    return r.headers.get("Content-Security-Policy", "")


def test_csp_presente(client):
    assert _csp(client), "CSP ausente na resposta"


def test_frame_src_permite_youtube(client):
    csp = _csp(client)
    # Isola a diretiva frame-src.
    frame = ""
    for parte in csp.split(";"):
        if parte.strip().startswith("frame-src"):
            frame = parte.strip()
            break
    assert frame, f"diretiva frame-src ausente na CSP: {csp!r}"
    assert "https://www.youtube.com" in frame, (
        f"frame-src não permite o YouTube (player não carregaria): {frame!r}"
    )


def test_frame_src_mantem_self(client):
    """Não pode remover 'self'/blob: ao permitir o YouTube (usados por outros embeds)."""
    csp = _csp(client)
    frame = next((p.strip() for p in csp.split(";") if p.strip().startswith("frame-src")), "")
    assert "'self'" in frame and "blob:" in frame

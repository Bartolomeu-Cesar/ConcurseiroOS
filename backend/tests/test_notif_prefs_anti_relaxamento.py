"""Testes das novas preferências de notificação anti-relaxamento:
hora de estudar, revisões do edital, queda de ritmo e marcos de streak.

Executar: pytest tests/test_notif_prefs_anti_relaxamento.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_notifprefs.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

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


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


_NOVOS = ["study_time_reminder", "study_time_hour", "edital_review_reminders",
          "pace_drop_alerts", "milestone_celebrations"]


def test_defaults_incluem_novos_campos(client):
    r = client.get("/api/push/preferences")
    assert r.status_code == 200
    data = r.json()
    for campo in _NOVOS:
        assert campo in data, f"campo {campo} ausente nos defaults"
    # Ligados por padrão; hora default 19.
    assert data["study_time_reminder"] is True
    assert data["edital_review_reminders"] is True
    assert data["pace_drop_alerts"] is True
    assert data["milestone_celebrations"] is True
    assert data["study_time_hour"] == 19


def test_update_persiste_novos_campos(client):
    payload = {
        "streak_reminders": True,
        "flashcard_reminders": True,
        "exam_reminders": True,
        "challenge_reminders": True,
        "quiet_hours_start": 22,
        "quiet_hours_end": 7,
        "study_time_reminder": False,
        "study_time_hour": 8,
        "edital_review_reminders": False,
        "pace_drop_alerts": False,
        "milestone_celebrations": False,
    }
    r = client.put("/api/push/preferences", json=payload)
    assert r.status_code == 200
    assert r.json()["ok"] is True

    got = client.get("/api/push/preferences").json()
    assert got["study_time_reminder"] is False
    assert got["study_time_hour"] == 8
    assert got["edital_review_reminders"] is False
    assert got["pace_drop_alerts"] is False
    assert got["milestone_celebrations"] is False


def test_study_time_hour_fora_do_range_422(client):
    payload = {
        "study_time_hour": 99,  # inválido (>23)
    }
    r = client.put("/api/push/preferences", json=payload)
    assert r.status_code == 422


def test_update_parcial_usa_defaults(client):
    # Corpo sem os novos campos deve assumir defaults (True) — schema pydantic.
    r = client.put("/api/push/preferences", json={"streak_reminders": True})
    assert r.status_code == 200
    got = client.get("/api/push/preferences").json()
    # Como o schema tem defaults True, o update grava True nos novos campos.
    assert got["milestone_celebrations"] is True


def test_check_triggers_roda_sem_erro(client):
    # Smoke: os novos triggers não devem quebrar o check-triggers.
    r = client.post("/api/push/check-triggers")
    assert r.status_code == 200
    assert isinstance(r.json(), dict)

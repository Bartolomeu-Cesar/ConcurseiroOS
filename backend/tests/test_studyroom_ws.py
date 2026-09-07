"""Testes do WebSocket real-time da Sala de Estudo.

Usa o TestClient (websocket_connect). AUTH_ENABLED=false → user 1.
Cobre: rejeição em sala inexistente, entrega de chat via tailer, presença,
e persistência da mensagem no banco.

Executar: pytest tests/test_studyroom_ws.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_sr_ws.db", delete=False)
_tmp_db.close()
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


def _criar_sala(client, titulo="Sala WS"):
    return client.post("/api/studyroom/criar", json={"titulo": titulo}).json()["codigo"]


def test_ws_sala_inexistente_fecha(client):
    # Conexão a sala inexistente é recusada: o servidor fecha o handshake antes
    # do accept. O tipo exato de exceção varia conforme a versão do TestClient
    # (WebSocketDisconnect / ClosedResourceError), então basta garantir que falha.
    with pytest.raises(Exception):  # noqa: B017, SIM117
        with client.websocket_connect("/api/studyroom/ws/ZZZZZZ") as ws:
            ws.receive_json()


def test_ws_recebe_presenca(client):
    codigo = _criar_sala(client)
    with client.websocket_connect(f"/api/studyroom/ws/{codigo}") as ws:
        # O tailer envia presença periodicamente; recebe ao menos um frame.
        msg = ws.receive_json()
        assert msg["type"] in ("presenca", "chat")
        # Eventualmente um frame de presença com o criador (user 1).
        for _ in range(5):
            if msg["type"] == "presenca":
                break
            msg = ws.receive_json()
        assert msg["type"] == "presenca"
        assert any(p["user_id"] == 1 for p in msg["participantes"])


def test_ws_chat_entregue_e_persistido(client):
    codigo = _criar_sala(client)
    with client.websocket_connect(f"/api/studyroom/ws/{codigo}") as ws:
        ws.send_json({"type": "chat", "mensagem": "Olá via WebSocket"})
        # O tailer deve entregar a mensagem em algum frame subsequente.
        recebido = None
        for _ in range(10):
            msg = ws.receive_json()
            if msg["type"] == "chat":
                textos = [m["mensagem"] for m in msg["mensagens"]]
                if "Olá via WebSocket" in textos:
                    recebido = msg
                    break
        assert recebido is not None

    # Persistiu no banco?
    c = sqlite3.connect(_tmp_db.name, timeout=10)
    try:
        row = c.execute(
            "SELECT COUNT(*) FROM study_room_chat WHERE mensagem = 'Olá via WebSocket'"
        ).fetchone()
        assert row[0] >= 1
    finally:
        c.close()


def test_ws_ping_pong(client):
    codigo = _criar_sala(client)
    with client.websocket_connect(f"/api/studyroom/ws/{codigo}") as ws:
        ws.send_json({"type": "ping"})
        # Pode vir frames de presença/chat antes do pong; procura o pong.
        achou = False
        for _ in range(10):
            msg = ws.receive_json()
            if msg.get("type") == "pong":
                achou = True
                break
        assert achou

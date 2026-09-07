"""WebSocket real-time da Sala de Estudo.

Objetivo: entregar chat, presença e timer com baixa latência, substituindo (com
fallback) o polling de 3s. Restrição de infra: o app roda com 2 workers uvicorn,
então um registry em memória NÃO cruza workers. Solução sem dependências extras
(sem Redis), coerente com o ethos SQLite do projeto:

- Cada worker mantém seu próprio registry de conexões por sala (_rooms).
- Um ÚNICO "tailer" por worker roda em background: a cada ~1s lê deltas do banco
  (novas linhas de study_room_chat e o snapshot de participantes) e faz push para
  as conexões locais daquela sala. Como todos os workers leem o MESMO SQLite, uma
  mensagem gravada pelo worker B é entregue pelas conexões do worker A — cross-worker
  seguro, sem broadcast em memória entre processos.
- Mensagem de chat recebida via WS é apenas GRAVADA no banco; a entrega (para todos,
  inclusive o autor e outros workers) fica a cargo do tailer — fonte única, sem
  duplicação.

Auth: token JWT via query (?token=), pois o WebSocket do navegador não envia header
Authorization. Reutiliza deps._decode_user_id. Se AUTH_ENABLED=false, usa user 1.
"""

import asyncio
import contextlib
from datetime import datetime

from deps import _decode_user_id
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

import database
from logger import log
from settings import settings

from .helpers import get_user_name

router = APIRouter(prefix="/api/studyroom", tags=["Study Room"])

# Registry por-worker: código da sala -> conjunto de conexões WebSocket.
_rooms: dict[str, set[WebSocket]] = {}
# Último id de chat já entregue por sala (evita reenviar histórico).
_last_chat_id: dict[str, int] = {}
# Task do tailer (uma por worker).
_tailer_task: asyncio.Task | None = None
_POLL_SEC = 1.0


def _open_conn():
    """Conexão sqlite crua para uso fora do ciclo de request (tailer/handshake)."""
    import sqlite3

    conn = sqlite3.connect(database.DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


async def _broadcast(codigo: str, payload: dict):
    """Envia payload a todas as conexões locais da sala; remove as mortas."""
    conns = list(_rooms.get(codigo, set()))
    mortas = []
    for ws in conns:
        try:
            await ws.send_json(payload)
        except Exception:
            mortas.append(ws)
    for ws in mortas:
        _rooms.get(codigo, set()).discard(ws)


def _room_snapshot(conn, codigo: str):
    """Lê participantes + novas mensagens de chat (id > last) de uma sala."""
    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        return None
    room_id = room["id"]

    participantes = [
        {
            "user_id": p["user_id"],
            "nome": p["nome"],
            "status": p["status"],
            "tempo_estudado": p["tempo_estudado_seg"],
        }
        for p in conn.execute(
            "SELECT user_id, nome, status, tempo_estudado_seg FROM study_room_participants "
            "WHERE room_id = ? ORDER BY joined_at",
            (room_id,),
        ).fetchall()
    ]

    last = _last_chat_id.get(codigo, 0)
    novas = conn.execute(
        "SELECT id, user_id, nome, mensagem, created_at FROM study_room_chat WHERE room_id = ? AND id > ? ORDER BY id",
        (room_id, last),
    ).fetchall()
    chat = [
        {
            "id": m["id"],
            "user_id": m["user_id"],
            "nome": m["nome"],
            "mensagem": m["mensagem"],
            "created_at": m["created_at"],
        }
        for m in novas
    ]
    if chat:
        _last_chat_id[codigo] = chat[-1]["id"]
    return {"participantes": participantes, "chat": chat}


async def _tailer_loop():
    """Loop único por worker: faz push de deltas do DB para as conexões locais."""
    while True:
        try:
            salas_ativas = [c for c, conns in _rooms.items() if conns]
            if salas_ativas:
                with database.get_db() as conn:
                    for codigo in salas_ativas:
                        snap = _room_snapshot(conn, codigo)
                        if snap is None:
                            continue
                        # Chat: só envia se houver mensagens novas.
                        if snap["chat"]:
                            await _broadcast(codigo, {"type": "chat", "mensagens": snap["chat"]})
                        # Presença: envia snapshot atual (leve; permite status/timer ao vivo).
                        await _broadcast(codigo, {"type": "presenca", "participantes": snap["participantes"]})
        except Exception as e:  # nunca deixa o loop morrer
            log.warning(f"studyroom ws tailer error: {e}")
        await asyncio.sleep(_POLL_SEC)


def _ensure_tailer():
    global _tailer_task
    if _tailer_task is None or _tailer_task.done():
        _tailer_task = asyncio.create_task(_tailer_loop())


@router.websocket("/ws/{codigo}")
async def studyroom_ws(websocket: WebSocket, codigo: str):
    """WebSocket da sala. Query: ?token=<jwt> (obrigatório se AUTH_ENABLED)."""
    codigo = codigo.upper()

    # Auth via query token (browser WS não manda header Authorization).
    user_id = 1
    if settings.AUTH_ENABLED:
        token = websocket.query_params.get("token")
        if not token:
            await websocket.close(code=4401)
            return
        try:
            user_id = _decode_user_id(token)
        except Exception:
            await websocket.close(code=4401)
            return

    # Valida que a sala existe e que o usuário é participante.
    conn = _open_conn()
    try:
        room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
        if not room:
            await websocket.close(code=4404)
            return
        room_id = room["id"]
        participa = conn.execute(
            "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
            (room_id, user_id),
        ).fetchone()
        if not participa:
            await websocket.close(code=4403)
            return
        nome = get_user_name(conn, user_id)
    finally:
        conn.close()

    await websocket.accept()
    _rooms.setdefault(codigo, set()).add(websocket)
    # Inicializa o ponteiro de chat sem reenviar histórico antigo (o REST já traz).
    if codigo not in _last_chat_id:
        c2 = _open_conn()
        try:
            last = c2.execute(
                "SELECT COALESCE(MAX(id), 0) AS m FROM study_room_chat WHERE room_id = ?",
                (room_id,),
            ).fetchone()["m"]
            _last_chat_id[codigo] = last
        finally:
            c2.close()
    _ensure_tailer()

    try:
        while True:
            data = await websocket.receive_json()
            tipo = data.get("type")
            if tipo == "chat":
                mensagem = str(data.get("mensagem", "")).strip()[:500]
                if not mensagem:
                    continue
                # Apenas grava; o tailer entrega a todos (inclusive outros workers).
                c = _open_conn()
                try:
                    c.execute(
                        "INSERT INTO study_room_chat (room_id, user_id, nome, mensagem, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (room_id, user_id, nome, mensagem, datetime.now().isoformat()),
                    )
                    c.commit()
                finally:
                    c.close()
            elif tipo == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        log.warning(f"studyroom ws recv error: {e}")
    finally:
        _rooms.get(codigo, set()).discard(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()

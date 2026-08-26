"""Chat direto entre amigos: enviar, listar conversas, ler mensagens, áudio."""
import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from database import get_db_session
from deps import get_user_id
from logger import log

from .helpers import _ensure_messages_table, _are_friends, _get_friend_ids

router = APIRouter(prefix="", tags=["Social"])

# Diretório para áudios do chat
AUDIO_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "data", "chat_audio")
os.makedirs(AUDIO_DIR, exist_ok=True)

@router.post("/api/social/chat/send")
def send_message(
    receiver_id: int = Body(..., embed=True),
    mensagem: str = Body(..., embed=True),
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Enviar mensagem direta para um amigo."""
    _ensure_messages_table(db)

    if not mensagem or not mensagem.strip():
        raise HTTPException(status_code=400, detail="Mensagem não pode ser vazia.")
    if len(mensagem) > 1000:
        raise HTTPException(status_code=400, detail="Mensagem muito longa (máx. 1000 caracteres).")
    if receiver_id == user_id:
        raise HTTPException(status_code=400, detail="Não é possível enviar mensagem para si mesmo.")

    # Verificar se são amigos
    if not _are_friends(db, user_id, receiver_id):
        raise HTTPException(status_code=403, detail="Vocês não são amigos. Adicione primeiro.")

    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO direct_messages (sender_id, receiver_id, mensagem, lida, created_at) VALUES (?, ?, ?, 0, ?)",
        (user_id, receiver_id, mensagem.strip(), now)
    )
    db.commit()

    log.info(f"[chat] Message sent from {user_id} to {receiver_id}")
    return {"ok": True, "created_at": now}


@router.get("/api/social/chat/unread/count")
def unread_count(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna contagem total de mensagens não lidas (para badge/polling)."""
    _ensure_messages_table(db)
    count = db.execute(
        "SELECT COUNT(*) FROM direct_messages WHERE receiver_id = ? AND lida = 0",
        (user_id,)
    ).fetchone()[0]
    return {"unread": count}


@router.get("/api/social/chat/conversations")
def list_conversations(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista conversas ativas com última mensagem e contagem de não lidas."""
    _ensure_messages_table(db)

    friend_ids = _get_friend_ids(db, user_id)

    conversations = []
    for fid in friend_ids:
        # Última mensagem da conversa
        last_msg = db.execute(
            """SELECT id, sender_id, mensagem, created_at FROM direct_messages
               WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
               ORDER BY id DESC LIMIT 1""",
            (user_id, fid, fid, user_id)
        ).fetchone()

        # Não lidas (recebidas por mim)
        unread = db.execute(
            "SELECT COUNT(*) FROM direct_messages WHERE sender_id = ? AND receiver_id = ? AND lida = 0",
            (fid, user_id)
        ).fetchone()[0]

        # Info do amigo
        friend_info = db.execute(
            "SELECT id, nome, username FROM users WHERE id = ?", (fid,)
        ).fetchone()

        conversations.append({
            "friend_id": fid,
            "nome": friend_info["nome"] if friend_info else f"User {fid}",
            "username": friend_info["username"] if friend_info else "",
            "ultima_mensagem": last_msg["mensagem"][:80] if last_msg else "",
            "ultima_mensagem_minha": last_msg["sender_id"] == user_id if last_msg else False,
            "created_at": last_msg["created_at"] if last_msg else "",
            "nao_lidas": unread,
        })

    # Ordenar: não lidas primeiro, depois por data da última msg (mais recente primeiro)
    conversations.sort(key=lambda x: (-x["nao_lidas"], x["created_at"] or ""), reverse=False)
    conversations.sort(key=lambda x: x["created_at"] or "", reverse=True)
    conversations.sort(key=lambda x: x["nao_lidas"], reverse=True)

    total_unread = sum(c["nao_lidas"] for c in conversations)
    return {"conversations": conversations, "total_unread": total_unread}


@router.get("/api/social/chat/{friend_id}")
def get_messages(
    friend_id: int,
    limit: int = 50,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna mensagens entre o user e um amigo."""
    _ensure_messages_table(db)

    if not _are_friends(db, user_id, friend_id):
        raise HTTPException(status_code=403, detail="Vocês não são amigos.")

    limit = min(limit, 100)

    rows = db.execute(
        """SELECT id, sender_id, receiver_id, mensagem, tipo, audio_path, lida, created_at
           FROM direct_messages
           WHERE (sender_id = ? AND receiver_id = ?) OR (sender_id = ? AND receiver_id = ?)
           ORDER BY id DESC LIMIT ?""",
        (user_id, friend_id, friend_id, user_id, limit)
    ).fetchall()

    # Marcar mensagens recebidas como lidas
    db.execute(
        "UPDATE direct_messages SET lida = 1 WHERE sender_id = ? AND receiver_id = ? AND lida = 0",
        (friend_id, user_id)
    )
    db.commit()

    messages = [
        {
            "id": r["id"],
            "sender_id": r["sender_id"],
            "mensagem": r["mensagem"],
            "tipo": r["tipo"] if "tipo" in r.keys() else "text",
            "audio_url": f"/api/social/chat/audio/{r['audio_path']}" if "audio_path" in r.keys() and r["audio_path"] else None,
            "is_mine": r["sender_id"] == user_id,
            "lida": bool(r["lida"]),
            "created_at": r["created_at"],
        }
        for r in reversed(rows)
    ]

    return {"messages": messages, "friend_id": friend_id}




@router.post("/api/social/chat/send-audio")
async def send_audio_message(
    receiver_id: int = Form(...),
    audio: UploadFile = File(...),
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Enviar mensagem de áudio para um amigo."""
    _ensure_messages_table(db)

    if receiver_id == user_id:
        raise HTTPException(status_code=400, detail="Não é possível enviar mensagem para si mesmo.")
    if not _are_friends(db, user_id, receiver_id):
        raise HTTPException(status_code=403, detail="Vocês não são amigos.")

    # Validar tipo de arquivo
    content_type = audio.content_type or ""
    if not content_type.startswith("audio/"):
        raise HTTPException(status_code=400, detail="Arquivo deve ser um áudio.")

    # Limitar tamanho (5MB)
    content = await audio.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Áudio muito grande (máx. 5MB).")

    # Salvar arquivo
    ext = "webm" if "webm" in content_type else "ogg" if "ogg" in content_type else "mp3"
    filename = f"{user_id}_{receiver_id}_{uuid.uuid4().hex[:12]}.{ext}"
    filepath = os.path.join(AUDIO_DIR, filename)

    with open(filepath, "wb") as f:
        f.write(content)

    # Inserir mensagem do tipo audio
    now = datetime.now().isoformat()
    db.execute(
        "INSERT INTO direct_messages (sender_id, receiver_id, mensagem, tipo, audio_path, lida, created_at) VALUES (?, ?, ?, 'audio', ?, 0, ?)",
        (user_id, receiver_id, "🎤 Áudio", filename, now)
    )
    db.commit()

    log.info(f"[chat] Audio sent from {user_id} to {receiver_id} ({len(content)} bytes)")
    return {"ok": True, "created_at": now, "audio_url": f"/api/social/chat/audio/{filename}"}


@router.get("/api/social/chat/audio/{filename}")
def get_audio(filename: str, db=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Servir arquivo de áudio do chat."""
    # Segurança: impedir path traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido.")

    filepath = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(filepath):
        raise HTTPException(status_code=404, detail="Áudio não encontrado.")

    # Verificar que o user é participante da conversa (sender ou receiver)
    msg = db.execute(
        "SELECT sender_id, receiver_id FROM direct_messages WHERE audio_path = ? LIMIT 1",
        (filename,)
    ).fetchone()
    if not msg or (msg["sender_id"] != user_id and msg["receiver_id"] != user_id):
        raise HTTPException(status_code=403, detail="Acesso negado.")

    ext = filename.rsplit(".", 1)[-1] if "." in filename else "webm"
    media_type = f"audio/{ext}" if ext in ("webm", "ogg", "mp3", "wav") else "audio/webm"
    return FileResponse(filepath, media_type=media_type)

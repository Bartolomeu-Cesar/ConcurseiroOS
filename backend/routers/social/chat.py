"""Chat direto entre amigos: enviar, listar conversas, ler mensagens."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log

from .helpers import _ensure_messages_table, _are_friends, _get_friend_ids

router = APIRouter(prefix="", tags=["Social"])

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
        """SELECT id, sender_id, receiver_id, mensagem, lida, created_at
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
            "is_mine": r["sender_id"] == user_id,
            "lida": bool(r["lida"]),
            "created_at": r["created_at"],
        }
        for r in reversed(rows)
    ]

    return {"messages": messages, "friend_id": friend_id}



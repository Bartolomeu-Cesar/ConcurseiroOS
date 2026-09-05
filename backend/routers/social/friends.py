"""Friendships: listar, adicionar, aceitar, rejeitar, remover amigos."""
from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from logger import log
from utils import today_str

from .helpers import AddFriendRequest

router = APIRouter(prefix="", tags=["Social"])

@router.get("/api/social/friends")
def list_friends(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """List user's friends (accepted status)."""
    log.info(f"[social] list_friends user_id={user_id}")
    try:
        rows = db.execute(
            """SELECT f.id,
                      CASE WHEN f.user_a = ? THEN f.user_b ELSE f.user_a END as friend_id,
                      f.created_at
               FROM friendships f
               WHERE f.status = 'accepted' AND (f.user_a = ? OR f.user_b = ?)""",
            (user_id, user_id, user_id)
        ).fetchall()
    except Exception:
        # Table may not exist yet - create it
        db.execute("""
            CREATE TABLE IF NOT EXISTS friendships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_a INTEGER NOT NULL,
                user_b INTEGER NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)
        db.commit()
        return {"friends": []}

    friends = []
    # Reusa a MESMA derivação de presença do widget (status.py) para que a lista
    # de amigos e o widget "Amigos ativos" fiquem consistentes (mesmo nome e
    # mesmo online/offline). Antes, esta rota só retornava `username` e nenhum
    # status → o frontend caía no fallback fixo `'online'` e num nome diferente.
    from .status import STATUS_VALIDOS, _is_online

    for r in rows:
        friend_info = db.execute(
            """SELECT u.id, u.nome, u.username, u.avatar,
                      s.status, s.materia, s.atualizado_em
               FROM users u
               LEFT JOIN user_status s ON s.user_id = u.id
               WHERE u.id = ?""",
            (r["friend_id"],)
        ).fetchone()

        if not friend_info:
            friends.append({
                "friendship_id": r["id"],
                "user_id": r["friend_id"],
                "nome": "Desconhecido",
                "username": "Desconhecido",
                "avatar": "👤",
                "online": False,
                "status": "offline",
                "status_label": STATUS_VALIDOS["offline"]["label"],
                "status_emoji": STATUS_VALIDOS["offline"]["emoji"],
                "materia": "",
                "created_at": r["created_at"],
            })
            continue

        status_raw = friend_info["status"] or "offline"
        online = _is_online(friend_info["atualizado_em"]) and status_raw != "offline"
        if not online:
            status_raw = "offline"
        info = STATUS_VALIDOS.get(status_raw, STATUS_VALIDOS["offline"])

        friends.append({
            "friendship_id": r["id"],
            "user_id": r["friend_id"],
            "nome": friend_info["nome"] or friend_info["username"] or f"Concurseiro #{friend_info['id']}",
            "username": friend_info["username"] or "",
            "avatar": friend_info["avatar"] or "👤",
            "online": online,
            "status": status_raw,
            "status_label": info["label"],
            "status_emoji": info["emoji"],
            "materia": (friend_info["materia"] or "") if online else "",
            "created_at": r["created_at"],
        })

    # Online primeiro, depois por nome (mesma ordenação do widget de presença).
    friends.sort(key=lambda a: (not a["online"], a["nome"].lower()))

    return {"friends": friends}


@router.get("/api/social/friends/pending")
def list_pending_requests(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """List pending friend requests (both received and sent)."""
    log.info(f"[social] list_pending_requests user_id={user_id}")
    try:
        # Received requests (where I am user_b)
        received = db.execute(
            """SELECT f.id, f.user_a as other_id, f.created_at, 'received' as direction
               FROM friendships f
               WHERE f.user_b = ? AND f.status = 'pending'
               ORDER BY f.created_at DESC""",
            (user_id,)
        ).fetchall()

        # Sent requests (where I am user_a)
        sent = db.execute(
            """SELECT f.id, f.user_b as other_id, f.created_at, 'sent' as direction
               FROM friendships f
               WHERE f.user_a = ? AND f.status = 'pending'
               ORDER BY f.created_at DESC""",
            (user_id,)
        ).fetchall()
    except Exception:
        return {"pending": [], "sent": []}

    pending = []
    for r in received:
        sender_info = db.execute(
            "SELECT id, nome, username, email FROM users WHERE id = ?", (r["other_id"],)
        ).fetchone()
        pending.append({
            "friendship_id": r["id"],
            "sender_id": r["other_id"],
            "nome": sender_info["nome"] if sender_info else "Desconhecido",
            "username": sender_info["username"] if sender_info else "",
            "email": sender_info["email"] if sender_info else "",
            "created_at": r["created_at"],
        })

    sent_list = []
    for r in sent:
        target_info = db.execute(
            "SELECT id, nome, username, email FROM users WHERE id = ?", (r["other_id"],)
        ).fetchone()
        sent_list.append({
            "friendship_id": r["id"],
            "target_id": r["other_id"],
            "nome": target_info["nome"] if target_info else "Desconhecido",
            "username": target_info["username"] if target_info else "",
            "email": target_info["email"] if target_info else "",
            "created_at": r["created_at"],
        })

    return {"pending": pending, "sent": sent_list}

@router.post("/api/social/friends/add")
def add_friend(
    body: AddFriendRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Send friend request by email or user_id."""
    log.info(f"[social] add_friend user_id={user_id} body={body}")

    if not body.email and not body.user_id:
        raise HTTPException(status_code=400, detail="Informe email ou user_id.")

    target = None
    if body.user_id:
        target = db.execute("SELECT id FROM users WHERE id = ?", (body.user_id,)).fetchone()
    elif body.email:
        target = db.execute("SELECT id FROM users WHERE email = ?", (body.email,)).fetchone()

    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    target_id = target["id"]

    if target_id == user_id:
        raise HTTPException(status_code=400, detail="Não é possível adicionar a si mesmo.")

    # Check if friendship already exists
    existing = db.execute(
        """SELECT id, status FROM friendships
           WHERE (user_a = ? AND user_b = ?) OR (user_a = ? AND user_b = ?)""",
        (user_id, target_id, target_id, user_id)
    ).fetchone()

    if existing:
        if existing["status"] == "accepted":
            raise HTTPException(status_code=400, detail="Vocês já são amigos.")
        elif existing["status"] == "pending":
            raise HTTPException(status_code=400, detail="Solicitação já enviada.")
        else:
            # Re-send if previously rejected
            db.execute(
                "UPDATE friendships SET status = 'pending', created_at = ? WHERE id = ?",
                (today_str(), existing["id"])
            )
            db.commit()
            return {"message": "Solicitação de amizade reenviada.", "friendship_id": existing["id"]}

    db.execute(
        "INSERT INTO friendships (user_a, user_b, status, created_at) VALUES (?, ?, 'pending', ?)",
        (user_id, target_id, today_str())
    )
    db.commit()

    friendship_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    return {"message": "Solicitação de amizade enviada.", "friendship_id": friendship_id}


@router.post("/api/social/friends/{id}/accept")
def accept_friend(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Accept a pending friend request."""
    log.info(f"[social] accept_friend id={id} user_id={user_id}")

    row = db.execute(
        "SELECT * FROM friendships WHERE id = ? AND user_b = ? AND status = 'pending'",
        (id, user_id)
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")

    db.execute("UPDATE friendships SET status = 'accepted' WHERE id = ?", (id,))
    db.commit()

    return {"message": "Amizade aceita."}


@router.post("/api/social/friends/{id}/reject")
def reject_friend(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Reject a pending friend request."""
    log.info(f"[social] reject_friend id={id} user_id={user_id}")

    row = db.execute(
        "SELECT * FROM friendships WHERE id = ? AND user_b = ? AND status = 'pending'",
        (id, user_id)
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Solicitação não encontrada.")

    db.execute("UPDATE friendships SET status = 'rejected' WHERE id = ?", (id,))
    db.commit()

    return {"message": "Solicitação rejeitada."}


@router.delete("/api/social/friends/{id}")
def remove_friend(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Remove a friend."""
    log.info(f"[social] remove_friend id={id} user_id={user_id}")

    row = db.execute(
        """SELECT * FROM friendships WHERE id = ? AND status = 'accepted'
           AND (user_a = ? OR user_b = ?)""",
        (id, user_id, user_id)
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Amizade não encontrada.")

    db.execute("DELETE FROM friendships WHERE id = ?", (id,))
    db.commit()

    return {"message": "Amigo removido."}


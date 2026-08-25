"""
Social Study Groups router for ConcurseiroOS.
Handles friendships, study groups, activity feed, and public profiles.
"""

import json
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from database import get_db_session
from deps import get_user_id
from logger import log
from sanitize import sanitize_input
from schemas import AddMemberRequest, ChangeMemberRoleRequest
from utils import today_str


# === Pydantic Models ===

class AddFriendRequest(BaseModel):
    email: Optional[str] = None
    user_id: Optional[int] = None


class CreateGroupRequest(BaseModel):
    nome: str
    descricao: str = ""
    edital_nome: str = ""
    max_membros: int = 20
    publico: bool = True


class GroupChallengeRequest(BaseModel):
    titulo: str
    meta_tipo: str
    meta_valor: int
    dias: int = 7


class PostActivityRequest(BaseModel):
    tipo: str
    descricao: str
    dados: Dict[str, Any] = {}


# === Router ===

router = APIRouter(prefix="", tags=["Social"])


# ============================================================
# DIRECT MESSAGES (Chat 1-a-1 entre amigos)
# ============================================================

def _ensure_messages_table(db):
    """Cria tabela de mensagens diretas se não existir."""
    db.execute("""
        CREATE TABLE IF NOT EXISTS direct_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            mensagem TEXT NOT NULL,
            lida INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        )
    """)
    db.execute("CREATE INDEX IF NOT EXISTS idx_dm_sender ON direct_messages(sender_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dm_receiver ON direct_messages(receiver_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_dm_pair ON direct_messages(sender_id, receiver_id)")
    db.commit()


# === Helper Functions ===

def _are_friends(db, user_a: int, user_b: int) -> bool:
    """Check if two users are friends (accepted status)."""
    try:
        row = db.execute(
            """SELECT id FROM friendships
               WHERE status = 'accepted'
                 AND ((user_a = ? AND user_b = ?) OR (user_a = ? AND user_b = ?))""",
            (user_a, user_b, user_b, user_a)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _share_group(db, user_a: int, user_b: int) -> bool:
    """Check if two users share at least one group."""
    try:
        row = db.execute(
            """SELECT gm1.group_id FROM group_members gm1
               INNER JOIN group_members gm2 ON gm1.group_id = gm2.group_id
               WHERE gm1.user_id = ? AND gm2.user_id = ?
               LIMIT 1""",
            (user_a, user_b)
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _can_view_profile(db, viewer_id: int, target_id: int) -> bool:
    """Check if viewer can see target's profile (friends or same group)."""
    if viewer_id == target_id:
        return True
    return _are_friends(db, viewer_id, target_id) or _share_group(db, viewer_id, target_id)


def _get_friend_ids(db, user_id: int) -> List[int]:
    """Get list of friend user IDs for a user."""
    try:
        rows = db.execute(
            """SELECT CASE WHEN user_a = ? THEN user_b ELSE user_a END as friend_id
               FROM friendships
               WHERE status = 'accepted' AND (user_a = ? OR user_b = ?)""",
            (user_id, user_id, user_id)
        ).fetchall()
        return [r["friend_id"] for r in rows]
    except Exception:
        return []


def _is_group_admin(db, group_id: int, user_id: int) -> bool:
    """Check if user is admin/creator of a group."""
    row = db.execute(
        """SELECT role FROM group_members
           WHERE group_id = ? AND user_id = ? AND role IN ('admin', 'creator')""",
        (group_id, user_id)
    ).fetchone()
    return row is not None


# === FRIENDSHIPS ===

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
    for r in rows:
        friend_info = db.execute(
            "SELECT id, username FROM users WHERE id = ?", (r["friend_id"],)
        ).fetchone()
        friends.append({
            "friendship_id": r["id"],
            "user_id": r["friend_id"],
            "username": friend_info["username"] if friend_info else "Desconhecido",
            "created_at": r["created_at"]
        })

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


# ============================================================
# CHAT ENDPOINTS
# ============================================================


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

    # Ordenar: não lidas primeiro, depois por data da última msg
    conversations.sort(key=lambda x: (-(x["nao_lidas"]), -(x["created_at"] or "")), reverse=False)

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


@router.get("/api/social/friends/pending")
def pending_requests(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """List pending friend requests (incoming)."""
    log.info(f"[social] pending_requests user_id={user_id}")

    try:
        rows = db.execute(
            """SELECT f.id, f.user_a as from_user_id, f.created_at
               FROM friendships f
               WHERE f.user_b = ? AND f.status = 'pending'
               ORDER BY f.created_at DESC""",
            (user_id,)
        ).fetchall()
    except Exception:
        return {"pending": []}

    requests = []
    for r in rows:
        sender = db.execute(
            "SELECT id, username FROM users WHERE id = ?", (r["from_user_id"],)
        ).fetchone()
        requests.append({
            "friendship_id": r["id"],
            "from_user_id": r["from_user_id"],
            "from_username": sender["username"] if sender else "Desconhecido",
            "created_at": r["created_at"]
        })

    return {"pending": requests}


# === STUDY GROUPS ===

@router.get("/api/social/groups")
def list_groups(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """List groups user is member of."""
    log.info(f"[social] list_groups user_id={user_id}")

    try:
        rows = db.execute(
            """SELECT sg.*, gm.role, gm.joined_at
               FROM study_groups sg
               INNER JOIN group_members gm ON sg.id = gm.group_id
               WHERE gm.user_id = ?
               ORDER BY gm.joined_at DESC""",
            (user_id,)
        ).fetchall()
    except Exception:
        return {"groups": []}

    groups = []
    for r in rows:
        member_count = db.execute(
            "SELECT COUNT(*) as cnt FROM group_members WHERE group_id = ?", (r["id"],)
        ).fetchone()["cnt"]
        groups.append({
            "id": r["id"],
            "nome": r["nome"],
            "descricao": r["descricao"],
            "edital_nome": r["edital_nome"],
            "criador_id": r["criador_id"],
            "max_membros": r["max_membros"],
            "publico": bool(r["publico"]),
            "member_count": member_count,
            "my_role": r["role"],
            "joined_at": r["joined_at"],
            "created_at": r["created_at"]
        })

    return {"groups": groups}


@router.get("/api/social/groups/discover")
def discover_groups(
    q: str = Query("", description="Busca por nome ou edital"),
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """List public groups user can join."""
    log.info(f"[social] discover_groups user_id={user_id} q={q}")

    try:
        if q:
            rows = db.execute(
                """SELECT sg.* FROM study_groups sg
                   WHERE sg.publico = 1
                     AND sg.id NOT IN (SELECT group_id FROM group_members WHERE user_id = ?)
                     AND (sg.nome LIKE ? OR sg.edital_nome LIKE ?)
                   ORDER BY sg.created_at DESC
                   LIMIT 50""",
                (user_id, f"%{q}%", f"%{q}%")
            ).fetchall()
        else:
            rows = db.execute(
                """SELECT sg.* FROM study_groups sg
                   WHERE sg.publico = 1
                     AND sg.id NOT IN (SELECT group_id FROM group_members WHERE user_id = ?)
                   ORDER BY sg.created_at DESC
                   LIMIT 50""",
                (user_id,)
            ).fetchall()
    except Exception:
        return {"groups": []}

    groups = []
    for r in rows:
        member_count = db.execute(
            "SELECT COUNT(*) as cnt FROM group_members WHERE group_id = ?", (r["id"],)
        ).fetchone()["cnt"]
        groups.append({
            "id": r["id"],
            "nome": r["nome"],
            "descricao": r["descricao"],
            "edital_nome": r["edital_nome"],
            "max_membros": r["max_membros"],
            "member_count": member_count,
            "created_at": r["created_at"]
        })

    return {"groups": groups}


@router.post("/api/social/groups")
def create_group(
    body: CreateGroupRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Create a new study group."""
    log.info(f"[social] create_group user_id={user_id} nome={body.nome}")

    db.execute(
        """INSERT INTO study_groups (nome, descricao, edital_nome, criador_id, max_membros, publico, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (sanitize_input(body.nome), sanitize_input(body.descricao, max_length=2000),
         sanitize_input(body.edital_nome), user_id, body.max_membros, int(body.publico), today_str())
    )
    db.commit()

    group_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]

    # Add creator as member with 'creator' role
    db.execute(
        "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, 'creator', ?)",
        (group_id, user_id, today_str())
    )
    db.commit()

    return {"message": "Grupo criado com sucesso.", "group_id": group_id}


@router.post("/api/social/groups/{id}/join")
def join_group(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Join a public group."""
    log.info(f"[social] join_group group_id={id} user_id={user_id}")

    group = db.execute("SELECT * FROM study_groups WHERE id = ?", (id,)).fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")

    if not group["publico"]:
        raise HTTPException(status_code=403, detail="Este grupo é privado.")

    # Check if already member
    existing = db.execute(
        "SELECT id FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Você já é membro deste grupo.")

    # Check max members
    member_count = db.execute(
        "SELECT COUNT(*) as cnt FROM group_members WHERE group_id = ?", (id,)
    ).fetchone()["cnt"]
    if member_count >= group["max_membros"]:
        raise HTTPException(status_code=400, detail="Grupo lotado.")

    db.execute(
        "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
        (id, user_id, today_str())
    )
    db.commit()

    # Post activity
    db.execute(
        "INSERT INTO activity_feed (user_id, tipo, descricao, dados, created_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, "group_joined", f"Entrou no grupo {group['nome']}", json.dumps({"group_id": id}), today_str())
    )
    db.commit()

    return {"message": "Você entrou no grupo."}


@router.post("/api/social/groups/{id}/leave")
def leave_group(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Leave a group."""
    log.info(f"[social] leave_group group_id={id} user_id={user_id}")

    membership = db.execute(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id)
    ).fetchone()

    if not membership:
        raise HTTPException(status_code=404, detail="Você não é membro deste grupo.")

    if membership["role"] == "creator":
        # Transfer ownership or delete group if no other members
        other_member = db.execute(
            "SELECT id, user_id FROM group_members WHERE group_id = ? AND user_id != ? LIMIT 1",
            (id, user_id)
        ).fetchone()
        if other_member:
            db.execute(
                "UPDATE group_members SET role = 'creator' WHERE id = ?", (other_member["id"],)
            )
        else:
            # Delete group if no one else is in it
            db.execute("DELETE FROM group_challenges WHERE group_id = ?", (id,))
            db.execute("DELETE FROM group_members WHERE group_id = ?", (id,))
            db.execute("DELETE FROM study_groups WHERE id = ?", (id,))
            db.commit()
            return {"message": "Grupo excluído (sem membros restantes)."}

    db.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id))
    db.commit()

    return {"message": "Você saiu do grupo."}


@router.post("/api/social/groups/{id}/add-member", summary="Adicionar membro ao grupo",
             description="Adiciona um usuário ao grupo por email ou user_id. Apenas criador/admin pode adicionar.")
def add_member_to_group(
    id: int,
    body: AddMemberRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Adiciona membro a um grupo existente (criador ou admin pode convidar)."""
    log.info(f"[social] add_member group_id={id} user_id={user_id}")

    # Verificar se o grupo existe
    group = db.execute("SELECT * FROM study_groups WHERE id = ?", (id,)).fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")

    # Verificar se quem está adicionando é criador ou admin
    requester_role = db.execute(
        "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not requester_role or requester_role["role"] not in ("creator", "admin"):
        raise HTTPException(status_code=403, detail="Apenas o criador ou admin pode adicionar membros.")

    # Identificar o usuário alvo
    target_email = sanitize_input(body.email)
    target_user_id = body.user_id
    target_username = sanitize_input(body.username)

    target = None
    if target_user_id:
        target = db.execute("SELECT id, nome, email FROM users WHERE id = ?", (target_user_id,)).fetchone()
    elif target_email:
        target = db.execute("SELECT id, nome, email FROM users WHERE email = ?", (target_email,)).fetchone()
    elif target_username:
        target = db.execute("SELECT id, nome, email FROM users WHERE username = ?", (target_username,)).fetchone()

    if not target:
        raise HTTPException(status_code=404, detail="Usuário não encontrado. Verifique email ou username.")

    tid = target["id"]

    # Verificar se já é membro
    existing = db.execute(
        "SELECT id FROM group_members WHERE group_id = ? AND user_id = ?", (id, tid)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Este usuário já é membro do grupo.")

    # Verificar limite de membros
    member_count = db.execute(
        "SELECT COUNT(*) as cnt FROM group_members WHERE group_id = ?", (id,)
    ).fetchone()["cnt"]
    if member_count >= group["max_membros"]:
        raise HTTPException(status_code=400, detail="Grupo atingiu o limite máximo de membros.")

    # Adicionar membro
    db.execute(
        "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, ?, 'member', ?)",
        (id, tid, today_str())
    )

    # Post activity
    db.execute(
        "INSERT INTO activity_feed (user_id, tipo, descricao, dados, created_at) VALUES (?, ?, ?, ?, ?)",
        (tid, "group_joined", f"Foi adicionado ao grupo {group['nome']}", json.dumps({"group_id": id, "added_by": user_id}), today_str())
    )
    db.commit()

    log.info(f"[social] member added: user={tid} to group={id} by user={user_id}")
    return {"message": f"Membro adicionado ao grupo com sucesso.", "user_id": tid, "nome": target["nome"]}


@router.get("/api/social/groups/{id}/members", summary="Listar membros do grupo")
def list_group_members(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista todos os membros de um grupo com seus dados e roles."""
    group = db.execute("SELECT * FROM study_groups WHERE id = ?", (id,)).fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")

    members = db.execute("""
        SELECT gm.user_id, gm.role, gm.joined_at, u.nome, u.username, u.avatar, u.email
        FROM group_members gm
        LEFT JOIN users u ON u.id = gm.user_id
        WHERE gm.group_id = ?
        ORDER BY CASE gm.role WHEN 'creator' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END, gm.joined_at
    """, (id,)).fetchall()

    return {
        "group_id": id,
        "group_name": group["nome"],
        "max_membros": group["max_membros"],
        "total": len(members),
        "members": [{
            "user_id": m["user_id"],
            "nome": m["nome"] or "Usuário",
            "username": m["username"] or "",
            "avatar": m["avatar"] or "",
            "role": m["role"],
            "joined_at": m["joined_at"],
        } for m in members],
    }


@router.put("/api/social/groups/{id}/members/{member_id}/role", summary="Alterar role de membro")
def change_member_role(
    id: int,
    member_id: int,
    body: ChangeMemberRoleRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Altera a role de um membro (apenas criador pode promover/rebaixar)."""
    new_role = body.role
    if new_role not in ("admin", "member"):
        raise HTTPException(status_code=400, detail="Role deve ser 'admin' ou 'member'.")

    # Verificar se é criador
    requester = db.execute(
        "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not requester or requester["role"] != "creator":
        raise HTTPException(status_code=403, detail="Apenas o criador pode alterar roles.")

    # Verificar se o membro existe
    member = db.execute(
        "SELECT id, role FROM group_members WHERE group_id = ? AND user_id = ?", (id, member_id)
    ).fetchone()
    if not member:
        raise HTTPException(status_code=404, detail="Membro não encontrado no grupo.")

    if member["role"] == "creator":
        raise HTTPException(status_code=400, detail="Não é possível alterar a role do criador.")

    db.execute("UPDATE group_members SET role = ? WHERE group_id = ? AND user_id = ?", (new_role, id, member_id))
    db.commit()

    return {"message": f"Role alterada para '{new_role}'.", "user_id": member_id, "new_role": new_role}


@router.delete("/api/social/groups/{id}/members/{member_id}", summary="Remover membro do grupo")
def remove_member_from_group(
    id: int,
    member_id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Remove um membro do grupo (criador ou admin pode remover)."""
    # Verificar permissão
    requester = db.execute(
        "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not requester or requester["role"] not in ("creator", "admin"):
        raise HTTPException(status_code=403, detail="Apenas criador ou admin pode remover membros.")

    # Não pode remover o criador
    target = db.execute(
        "SELECT role FROM group_members WHERE group_id = ? AND user_id = ?", (id, member_id)
    ).fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="Membro não encontrado no grupo.")
    if target["role"] == "creator":
        raise HTTPException(status_code=400, detail="Não é possível remover o criador do grupo.")

    db.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = ?", (id, member_id))
    db.commit()

    return {"message": "Membro removido do grupo."}


@router.get("/api/social/groups/{id}")
def get_group_detail(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Get group details with members and their progress."""
    log.info(f"[social] get_group_detail group_id={id} user_id={user_id}")

    group = db.execute("SELECT * FROM study_groups WHERE id = ?", (id,)).fetchone()
    if not group:
        raise HTTPException(status_code=404, detail="Grupo não encontrado.")

    # Verify user is a member
    membership = db.execute(
        "SELECT * FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not membership:
        raise HTTPException(status_code=403, detail="Você não é membro deste grupo.")

    # Get members with basic info
    members_rows = db.execute(
        """SELECT gm.user_id, gm.role, gm.joined_at
           FROM group_members gm
           WHERE gm.group_id = ?
           ORDER BY gm.role DESC, gm.joined_at ASC""",
        (id,)
    ).fetchall()

    members = []
    for m in members_rows:
        user_info = db.execute(
            "SELECT id, username FROM users WHERE id = ?", (m["user_id"],)
        ).fetchone()

        # Try to get gamification stats if available
        stats = db.execute(
            "SELECT xp, streak, level FROM user_gamification WHERE user_id = ?", (m["user_id"],)
        ).fetchone()

        member_data = {
            "user_id": m["user_id"],
            "username": user_info["username"] if user_info else "Desconhecido",
            "role": m["role"],
            "joined_at": m["joined_at"],
            "xp": stats["xp"] if stats else 0,
            "streak": stats["streak"] if stats else 0,
            "level": stats["level"] if stats else 1,
        }
        members.append(member_data)

    # Get challenges
    challenges = db.execute(
        "SELECT * FROM group_challenges WHERE group_id = ? ORDER BY created_at DESC",
        (id,)
    ).fetchall()

    challenges_list = [
        {
            "id": c["id"],
            "titulo": c["titulo"],
            "meta_tipo": c["meta_tipo"],
            "meta_valor": c["meta_valor"],
            "dias": c["dias"],
            "created_at": c["created_at"]
        }
        for c in challenges
    ]

    return {
        "id": group["id"],
        "nome": group["nome"],
        "descricao": group["descricao"],
        "edital_nome": group["edital_nome"],
        "criador_id": group["criador_id"],
        "max_membros": group["max_membros"],
        "publico": bool(group["publico"]),
        "created_at": group["created_at"],
        "members": members,
        "challenges": challenges_list
    }


@router.get("/api/social/groups/{id}/ranking")
def group_ranking(
    id: int,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Get group leaderboard (XP this week)."""
    log.info(f"[social] group_ranking group_id={id} user_id={user_id}")

    # Verify user is a member
    membership = db.execute(
        "SELECT id FROM group_members WHERE group_id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not membership:
        raise HTTPException(status_code=403, detail="Você não é membro deste grupo.")

    members_rows = db.execute(
        "SELECT user_id FROM group_members WHERE group_id = ?", (id,)
    ).fetchall()

    ranking = []
    for m in members_rows:
        uid = m["user_id"]
        user_info = db.execute(
            "SELECT id, username FROM users WHERE id = ?", (uid,)
        ).fetchone()

        stats = db.execute(
            "SELECT xp, streak, level FROM user_gamification WHERE user_id = ?", (uid,)
        ).fetchone()

        # Weekly XP: count XP from activity in the last 7 days
        weekly = db.execute(
            """SELECT COALESCE(SUM(json_extract(dados, '$.xp')), 0) as weekly_xp
               FROM activity_feed
               WHERE user_id = ? AND created_at >= date('now', '-7 days')""",
            (uid,)
        ).fetchone()

        ranking.append({
            "user_id": uid,
            "username": user_info["username"] if user_info else "Desconhecido",
            "xp_total": stats["xp"] if stats else 0,
            "xp_semanal": weekly["weekly_xp"] if weekly else 0,
            "streak": stats["streak"] if stats else 0,
            "level": stats["level"] if stats else 1,
        })

    # Sort by weekly XP descending
    ranking.sort(key=lambda x: x["xp_semanal"], reverse=True)

    # Add position
    for i, r in enumerate(ranking):
        r["posicao"] = i + 1

    return {"ranking": ranking, "group_id": id}


@router.post("/api/social/groups/{id}/challenge")
def create_group_challenge(
    id: int,
    body: GroupChallengeRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Create a group challenge (only admin/creator)."""
    log.info(f"[social] create_group_challenge group_id={id} user_id={user_id}")

    if not _is_group_admin(db, id, user_id):
        raise HTTPException(status_code=403, detail="Apenas administradores podem criar desafios.")

    db.execute(
        """INSERT INTO group_challenges (group_id, titulo, meta_tipo, meta_valor, dias, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (id, body.titulo, body.meta_tipo, body.meta_valor, body.dias, today_str())
    )
    db.commit()

    challenge_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    return {"message": "Desafio criado.", "challenge_id": challenge_id}


# === ACTIVITY FEED ===

@router.get("/api/social/feed")
def get_activity_feed(
    limit: int = Query(30, ge=1, le=100),
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Get activity feed (user's own + friends' activities)."""
    log.info(f"[social] get_activity_feed user_id={user_id} limit={limit}")

    friend_ids = _get_friend_ids(db, user_id)
    visible_ids = [user_id] + friend_ids

    try:
        placeholders = ",".join("?" * len(visible_ids))
        rows = db.execute(
            f"""SELECT af.*, u.username
                FROM activity_feed af
                LEFT JOIN users u ON af.user_id = u.id
                WHERE af.user_id IN ({placeholders})
                ORDER BY af.created_at DESC
                LIMIT ?""",
            (*visible_ids, limit)
        ).fetchall()
    except Exception:
        return {"feed": []}

    feed = []
    for r in rows:
        dados = {}
        try:
            dados = json.loads(r["dados"]) if r["dados"] else {}
        except (json.JSONDecodeError, TypeError):
            pass

        feed.append({
            "id": r["id"],
            "user_id": r["user_id"],
            "username": r["username"] or "Desconhecido",
            "tipo": r["tipo"],
            "descricao": r["descricao"],
            "dados": dados,
            "created_at": r["created_at"]
        })

    return {"feed": feed}


@router.post("/api/social/feed/post")
def post_activity(
    body: PostActivityRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Record a new activity event."""
    log.info(f"[social] post_activity user_id={user_id} tipo={body.tipo}")

    valid_types = [
        "streak_milestone", "badge_earned", "challenge_complete",
        "simulado_complete", "level_up", "group_joined", "mastery_achieved"
    ]

    if body.tipo not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo inválido. Tipos válidos: {', '.join(valid_types)}"
        )

    db.execute(
        """INSERT INTO activity_feed (user_id, tipo, descricao, dados, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, body.tipo, body.descricao, json.dumps(body.dados, ensure_ascii=False), today_str())
    )
    db.commit()

    activity_id = db.execute("SELECT last_insert_rowid() as id").fetchone()["id"]
    return {"message": "Atividade registrada.", "activity_id": activity_id}


# === PROFILE ===

@router.get("/api/social/profile")
def get_my_profile(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Get user's social profile summary."""
    log.info(f"[social] get_my_profile user_id={user_id}")

    user = db.execute(
        "SELECT id, username FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    username = user["username"] if user else f"Concurseiro #{user_id}"

    # Gamification stats (from real data if user_gamification doesn't exist)
    try:
        stats = db.execute(
            "SELECT xp, streak, level FROM user_gamification WHERE user_id = ?", (user_id,)
        ).fetchone()
    except Exception:
        stats = None

    if not stats:
        # Fallback: calculate from actual data
        from utils import calculate_streak
        streak_info = calculate_streak(db, user_id)
        streak_val = streak_info["streak_atual"]
        horas = db.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?", (user_id,)).fetchone()[0]
        questoes = db.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
        xp_val = int(horas * 100 + questoes * 10)
        level_val = (xp_val // 500) + 1
    else:
        streak_val = stats["streak"]
        xp_val = stats["xp"]
        level_val = stats["level"]

    # Badges count
    try:
        badges = db.execute(
            "SELECT COUNT(*) as cnt FROM user_badges WHERE user_id = ?", (user_id,)
        ).fetchone()
        badges_count = badges["cnt"] if badges else 0
    except Exception:
        badges_count = 0

    # Friends count
    try:
        friends_count = db.execute(
            """SELECT COUNT(*) as cnt FROM friendships
               WHERE status = 'accepted' AND (user_a = ? OR user_b = ?)""",
            (user_id, user_id)
        ).fetchone()["cnt"]
    except Exception:
        friends_count = 0

    # Groups
    try:
        groups_count = db.execute(
            "SELECT COUNT(*) as cnt FROM group_members WHERE user_id = ?", (user_id,)
        ).fetchone()["cnt"]
    except Exception:
        groups_count = 0

    return {
        "user_id": user_id,
        "username": username,
        "streak": streak_val,
        "level": level_val,
        "xp": xp_val,
        "badges_count": badges_count,
        "friends_count": friends_count,
        "groups_count": groups_count
    }


@router.get("/api/social/profile/{user_id}")
def get_user_profile(
    user_id: int,
    db=Depends(get_db_session),
    current_user_id: int = Depends(get_user_id)
):
    """Get another user's public profile (if friends or same group)."""
    log.info(f"[social] get_user_profile target={user_id} viewer={current_user_id}")

    if not _can_view_profile(db, current_user_id, user_id):
        raise HTTPException(
            status_code=403,
            detail="Você não tem permissão para ver este perfil."
        )

    user = db.execute(
        "SELECT id, username FROM users WHERE id = ?", (user_id,)
    ).fetchone()

    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    stats = db.execute(
        "SELECT xp, streak, level FROM user_gamification WHERE user_id = ?", (user_id,)
    ).fetchone()

    badges = db.execute(
        "SELECT COUNT(*) as cnt FROM user_badges WHERE user_id = ?", (user_id,)
    ).fetchone()

    # Recent activity (last 10)
    recent_activity = db.execute(
        """SELECT tipo, descricao, created_at FROM activity_feed
           WHERE user_id = ?
           ORDER BY created_at DESC LIMIT 10""",
        (user_id,)
    ).fetchall()

    activities = [
        {"tipo": a["tipo"], "descricao": a["descricao"], "created_at": a["created_at"]}
        for a in recent_activity
    ]

    # Shared groups
    shared_groups = db.execute(
        """SELECT sg.id, sg.nome FROM study_groups sg
           INNER JOIN group_members gm1 ON sg.id = gm1.group_id AND gm1.user_id = ?
           INNER JOIN group_members gm2 ON sg.id = gm2.group_id AND gm2.user_id = ?""",
        (current_user_id, user_id)
    ).fetchall()

    return {
        "user_id": user_id,
        "username": user["username"],
        "streak": stats["streak"] if stats else 0,
        "level": stats["level"] if stats else 1,
        "xp": stats["xp"] if stats else 0,
        "badges_count": badges["cnt"] if badges else 0,
        "recent_activity": activities,
        "shared_groups": [{"id": g["id"], "nome": g["nome"]} for g in shared_groups],
        "is_friend": _are_friends(db, current_user_id, user_id)
    }

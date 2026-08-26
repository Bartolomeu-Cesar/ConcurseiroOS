"""Social helpers: Pydantic models e funções auxiliares."""
import json
from datetime import datetime
from typing import Optional, List, Dict, Any

from pydantic import BaseModel

from logger import log


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



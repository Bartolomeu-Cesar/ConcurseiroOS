"""Activity feed e perfis sociais."""
import json

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db_session
from logger import log
from utils import today_str

from .helpers import PostActivityRequest, _are_friends, _can_view_profile, _get_friend_ids

router = APIRouter(prefix="", tags=["Social"])

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

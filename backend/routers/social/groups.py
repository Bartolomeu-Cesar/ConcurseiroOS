"""Study Groups: CRUD, membros, ranking, desafios."""
import json

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException, Query
from sanitize import sanitize_input
from schemas import AddMemberRequest, ChangeMemberRoleRequest

from database import get_db_session
from logger import log
from utils import today_str

from .helpers import CreateGroupRequest, GroupChallengeRequest, _is_group_admin

router = APIRouter(prefix="", tags=["Social"])

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
    return {"message": "Membro adicionado ao grupo com sucesso.", "user_id": tid, "nome": target["nome"]}


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



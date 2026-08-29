"""
Router de Administração de Usuários.
Apenas user_id=1 (admin) pode acessar estes endpoints.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from plans import PLANS
from schemas import AdminCreateUser, AdminUpdateUser, AdminBulkAction, AdminChangePlan
from utils import today_str

router = APIRouter(prefix="/api/admin", tags=["Administração"])


def _require_admin(user_id: int):
    """Verifica se o usuário é administrador (role='admin')."""
    from database import get_db
    with get_db() as conn:
        user = conn.execute("SELECT role FROM users WHERE id = ?", (user_id,)).fetchone()
        if not user or user["role"] != "admin":
            raise HTTPException(status_code=403, detail="Acesso restrito ao administrador.")


# ============================================================
# LISTAR USUÁRIOS
# ============================================================

@router.get("/users", summary="Listar todos os usuários")
def list_users(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista todos os usuários com paginação e busca."""
    _require_admin(user_id)

    offset = (page - 1) * limit

    if search:
        total = conn.execute(
            "SELECT COUNT(*) FROM users WHERE nome LIKE ? OR email LIKE ? OR username LIKE ?",
            (f"%{search}%", f"%{search}%", f"%{search}%")
        ).fetchone()[0]
        rows = conn.execute("""
            SELECT id, email, nome, username, avatar, plano, plano_expira, created_at, last_login, email_verified, role
            FROM users WHERE nome LIKE ? OR email LIKE ? OR username LIKE ?
            ORDER BY id LIMIT ? OFFSET ?
        """, (f"%{search}%", f"%{search}%", f"%{search}%", limit, offset)).fetchall()
    else:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        rows = conn.execute("""
            SELECT id, email, nome, username, avatar, plano, plano_expira, created_at, last_login, email_verified, role
            FROM users ORDER BY id LIMIT ? OFFSET ?
        """, (limit, offset)).fetchall()

    users = []
    for r in rows:
        users.append({
            "id": r["id"],
            "email": r["email"],
            "nome": r["nome"],
            "username": r["username"],
            "avatar": r["avatar"],
            "plano": r["plano"],
            "plano_nome": PLANS.get(r["plano"], {}).get("nome", r["plano"]),
            "plano_expira": r["plano_expira"],
            "role": r["role"] or "user",
            "created_at": r["created_at"],
            "last_login": r["last_login"],
            "email_verified": bool(r["email_verified"]),
        })

    return {
        "users": users,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit,
    }


# ============================================================
# DETALHES DO USUÁRIO
# ============================================================

@router.get("/users/{uid}", summary="Detalhes de um usuário")
def get_user_detail(
    uid: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna detalhes completos de um usuário com estatísticas."""
    _require_admin(user_id)

    user = conn.execute(
        "SELECT id, email, nome, username, avatar, plano, plano_expira, created_at, last_login, email_verified FROM users WHERE id = ?",
        (uid,)
    ).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    # Estatísticas
    stats = {}
    stats["questoes_respondidas"] = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (uid,)
    ).fetchone()[0]
    stats["flashcards"] = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE user_id = ?", (uid,)
    ).fetchone()[0]
    stats["horas_total"] = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?", (uid,)
    ).fetchone()[0]
    stats["topicos_edital"] = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE user_id = ?", (uid,)
    ).fetchone()[0]
    stats["streak_atual"] = 0
    try:
        from utils import calculate_streak
        streak_info = calculate_streak(conn, uid)
        stats["streak_atual"] = streak_info.get("streak_atual", 0)
    except Exception:
        pass

    # Atividade recente (últimos 7 dias)
    sete_dias = (datetime.now().date().__class__.today() - __import__('datetime').timedelta(days=7)).isoformat()
    stats["dias_ativos_7d"] = conn.execute(
        "SELECT COUNT(DISTINCT data) FROM streaks WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0) AND user_id = ?",
        (sete_dias, uid)
    ).fetchone()[0]

    return {
        "user": dict(user),
        "stats": stats,
        "plano_info": PLANS.get(user["plano"], {}),
    }


# ============================================================
# CRIAR USUÁRIO
# ============================================================

@router.post("/users", summary="Criar novo usuário")
def create_user(
    body: AdminCreateUser,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Cria um novo usuário manualmente."""
    _require_admin(user_id)

    email = body.email.strip().lower()
    nome = body.nome.strip()
    username = body.username.strip()
    plano = body.plano
    password = body.password

    if not email:
        raise HTTPException(status_code=400, detail="Email é obrigatório.")

    # Verificar se email já existe
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email já cadastrado.")

    # Hash da senha se fornecida
    password_hash = ""
    if password:
        import bcrypt
        password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO users (email, nome, username, avatar, password_hash, plano, email_verified, created_at)
        VALUES (?, ?, ?, '', ?, ?, 1, ?)
    """, (email, nome, username, password_hash, plano, now))
    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Criar metas padrão para o novo usuário
    conn.execute("""
        INSERT OR IGNORE INTO metas_config (id, meta_horas, meta_questoes, meta_flashcards, meta_paginas, user_id)
        VALUES (?, 3.0, 30, 10, 20, ?)
    """, (new_id, new_id))

    conn.commit()
    log.info(f"[admin] User created: id={new_id} email={email} plano={plano}")
    return {"ok": True, "id": new_id, "email": email, "nome": nome, "plano": plano}


# ============================================================
# EDITAR USUÁRIO
# ============================================================

@router.put("/users/{uid}", summary="Editar usuário")
def update_user(
    uid: int,
    body: AdminUpdateUser,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Atualiza dados de um usuário (nome, email, username, plano, etc)."""
    _require_admin(user_id)

    user = conn.execute("SELECT id FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    updates = []
    params = []
    sent_fields = body.model_fields_set

    if "nome" in sent_fields:
        updates.append("nome = ?")
        params.append(body.nome.strip())
    if "email" in sent_fields:
        new_email = body.email.strip().lower()
        # Check uniqueness
        dup = conn.execute("SELECT id FROM users WHERE email = ? AND id != ?", (new_email, uid)).fetchone()
        if dup:
            raise HTTPException(status_code=409, detail="Email já usado por outro usuário.")
        updates.append("email = ?")
        params.append(new_email)
    if "username" in sent_fields:
        updates.append("username = ?")
        params.append(body.username.strip())
    if "plano" in sent_fields:
        if body.plano not in PLANS:
            raise HTTPException(status_code=400, detail=f"Plano inválido. Opções: {list(PLANS.keys())}")
        updates.append("plano = ?")
        params.append(body.plano)
    if "plano_expira" in sent_fields:
        updates.append("plano_expira = ?")
        params.append(body.plano_expira)
    if "avatar" in sent_fields:
        updates.append("avatar = ?")
        params.append(body.avatar)
    if "role" in sent_fields:
        if body.role not in ("admin", "user"):
            raise HTTPException(status_code=400, detail="Role deve ser 'admin' ou 'user'.")
        updates.append("role = ?")
        params.append(body.role)
    if "password" in sent_fields and body.password:
        import bcrypt
        updates.append("password_hash = ?")
        params.append(bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode())

    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar.")

    params.append(uid)
    conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()

    log.info(f"[admin] User updated: id={uid} fields={list(sent_fields)}")
    return {"ok": True, "updated_fields": list(sent_fields)}


# ============================================================
# EXCLUIR USUÁRIO
# ============================================================

@router.delete("/users/{uid}", summary="Excluir usuário")
def delete_user(
    uid: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Exclui um usuário e todos os seus dados. IRREVERSÍVEL."""
    _require_admin(user_id)

    if uid == 1:
        raise HTTPException(status_code=400, detail="Não é possível excluir o administrador.")

    user = conn.execute("SELECT id, nome, email FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    # Deletar todos os dados do usuário
    tables_with_user_id = [
        "edital", "flashcards", "questoes", "questoes_respostas",
        "simulados", "simulado_questoes", "ciclo_estudos", "sessoes_estudo",
        "streaks", "metas_config", "notas_pdf", "notas_topico",
        "bookmarks_pdf", "cadernos", "caderno_itens", "feynman",
        "desafios", "planejador_semanal", "calendario_personalizado",
        "calendario_atividades", "calendario_streaks", "resumos",
        "sumulas", "progress", "edital_info",
        "push_subscriptions", "notification_preferences", "notification_log",
        "ai_usage", "ai_conversations",
        "friendships", "group_members", "activity_feed",
        "user_gamification", "user_badges",
        "league_members", "league_history",
    ]

    deleted_counts = {}
    for table in tables_with_user_id:
        try:
            result = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
            deleted_counts[table] = result.rowcount
        except Exception:
            pass

    # Friendships (user_a or user_b)
    try:
        conn.execute("DELETE FROM friendships WHERE user_a = ? OR user_b = ?", (uid, uid))
    except Exception:
        pass

    # Finally delete the user
    conn.execute("DELETE FROM users WHERE id = ?", (uid,))
    conn.commit()

    log.info(f"[admin] User DELETED: id={uid} email={user['email']}")
    return {"ok": True, "deleted_user": {"id": uid, "nome": user["nome"], "email": user["email"]}}


# ============================================================
# ALTERAR PLANO
# ============================================================

@router.post("/users/{uid}/plano", summary="Alterar plano do usuário")
def change_plan(
    uid: int,
    body: AdminChangePlan,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Altera o plano de um usuário (upgrade/downgrade)."""
    _require_admin(user_id)

    if body.plano not in PLANS:
        raise HTTPException(status_code=400, detail=f"Plano inválido. Opções: {list(PLANS.keys())}")

    conn.execute("UPDATE users SET plano = ?, plano_expira = ? WHERE id = ?", (body.plano, body.plano_expira, uid))
    conn.commit()

    log.info(f"[admin] Plan changed: user={uid} → {body.plano} (expires={body.plano_expira})")
    return {"ok": True, "plano": body.plano, "plano_nome": PLANS[body.plano]["nome"], "plano_expira": body.plano_expira}


# ============================================================
# ESTATÍSTICAS GLOBAIS
# ============================================================

@router.get("/stats", summary="Estatísticas globais do sistema")
def global_stats(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna estatísticas gerais do sistema."""
    _require_admin(user_id)

    total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes").fetchone()[0]
    total_flashcards = conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0]
    total_respostas = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    total_horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]

    # Usuários por plano
    planos = conn.execute("SELECT plano, COUNT(*) as total FROM users GROUP BY plano").fetchall()
    planos_map = {r["plano"]: r["total"] for r in planos}

    # Usuários ativos (últimos 7 dias)
    sete_dias = (datetime.now().date().__class__.today() - __import__('datetime').timedelta(days=7)).isoformat()
    ativos_7d = conn.execute(
        "SELECT COUNT(DISTINCT user_id) FROM streaks WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0)",
        (sete_dias,)
    ).fetchone()[0]

    return {
        "total_users": total_users,
        "usuarios_por_plano": planos_map,
        "ativos_7d": ativos_7d,
        "total_questoes_banco": total_questoes,
        "total_flashcards": total_flashcards,
        "total_respostas": total_respostas,
        "total_horas_estudo": round(total_horas, 1),
    }


# ============================================================
# MONETIZAÇÃO — CONFIGURAÇÃO DINÂMICA
# ============================================================

@router.get("/monetizacao", summary="Ler configuração de monetização")
def get_monetizacao(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a configuração atual de monetização (janela vitalício, preços)."""
    _require_admin(user_id)
    from plans import _get_vitalicio_window, get_vitalicio_preco, get_creditos_precos, is_vitalicio_disponivel

    inicio, fim = _get_vitalicio_window()
    return {
        "vitalicio": {
            "venda_inicio": inicio,
            "venda_fim": fim,
            "preco": get_vitalicio_preco(),
            "status": is_vitalicio_disponivel(),
        },
        "creditos": {
            "precos": get_creditos_precos(),
        },
    }


@router.put("/monetizacao", summary="Atualizar configuração de monetização")
def update_monetizacao(
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Atualiza janela de venda do vitalício, preço e preços de créditos.

    body: {
        vitalicio_venda_inicio: "YYYY-MM-DD" (opcional),
        vitalicio_venda_fim: "YYYY-MM-DD" (opcional),
        vitalicio_preco: float (opcional),
        creditos_precos: {"1": 4.9, "5": 19.9, ...} (opcional)
    }
    """
    _require_admin(user_id)
    from plans import set_app_config
    from datetime import date
    import json

    updated = []

    if "vitalicio_venda_inicio" in body:
        val = str(body["vitalicio_venda_inicio"]).strip()
        if val:
            try:
                date.fromisoformat(val)  # Valida formato
            except ValueError:
                raise HTTPException(status_code=400, detail="vitalicio_venda_inicio deve ser YYYY-MM-DD")
        set_app_config(conn, "vitalicio_venda_inicio", val)
        updated.append("vitalicio_venda_inicio")

    if "vitalicio_venda_fim" in body:
        val = str(body["vitalicio_venda_fim"]).strip()
        if val:
            try:
                date.fromisoformat(val)
            except ValueError:
                raise HTTPException(status_code=400, detail="vitalicio_venda_fim deve ser YYYY-MM-DD")
        set_app_config(conn, "vitalicio_venda_fim", val)
        updated.append("vitalicio_venda_fim")

    if "vitalicio_preco" in body:
        try:
            preco = float(body["vitalicio_preco"])
            if preco < 0:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="vitalicio_preco deve ser número positivo")
        set_app_config(conn, "vitalicio_preco", str(preco))
        updated.append("vitalicio_preco")

    if "creditos_precos" in body:
        precos = body["creditos_precos"]
        if not isinstance(precos, dict):
            raise HTTPException(status_code=400, detail="creditos_precos deve ser objeto {qtd: preco}")
        # Validar
        try:
            {int(k): float(v) for k, v in precos.items()}
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="creditos_precos: chaves int e valores float")
        set_app_config(conn, "creditos_precos", json.dumps(precos))
        updated.append("creditos_precos")

    if not updated:
        raise HTTPException(status_code=400, detail="Nenhum campo válido para atualizar.")

    log.info(f"[admin] Monetização atualizada: {updated}")
    return {"ok": True, "updated": updated}


# ============================================================
# CRÉDITOS — BRINDE / AJUSTE MANUAL
# ============================================================

@router.post("/users/{uid}/creditos", summary="Adicionar créditos de brinde a um usuário")
def add_creditos_brinde(
    uid: int,
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Adiciona (ou remove, se negativo) créditos ao saldo de um usuário como brinde.

    body: {quantidade: int, motivo: str (opcional)}
    """
    _require_admin(user_id)

    quantidade = body.get("quantidade", 0)
    motivo = (body.get("motivo") or "Brinde do administrador").strip()

    if not isinstance(quantidade, int) or quantidade == 0:
        raise HTTPException(status_code=400, detail="quantidade deve ser inteiro diferente de zero")

    user = conn.execute("SELECT creditos_saldo FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    saldo_anterior = user[0] or 0
    saldo_posterior = max(0, saldo_anterior + quantidade)

    conn.execute("UPDATE users SET creditos_saldo = ? WHERE id = ?", (saldo_posterior, uid))

    # Registrar no histórico
    try:
        conn.execute("""
            INSERT INTO creditos_historico (user_id, tipo, quantidade, saldo_anterior, saldo_posterior, motivo, created_at)
            VALUES (?, 'brinde_admin', ?, ?, ?, ?, ?)
        """, (uid, quantidade, saldo_anterior, saldo_posterior, motivo, datetime.now().isoformat()))
    except Exception:
        pass

    conn.commit()
    log.info(f"[admin] Créditos brinde: user={uid} {quantidade:+d} (saldo {saldo_anterior}→{saldo_posterior}) motivo={motivo}")
    return {"ok": True, "saldo_anterior": saldo_anterior, "saldo_posterior": saldo_posterior, "quantidade": quantidade}


# ============================================================
# ATIVAÇÃO RÁPIDA DE PLANO (PRÊMIO)
# ============================================================

@router.post("/users/{uid}/ativar-plano", summary="Ativar Premium ou Vitalício como prêmio")
def ativar_plano_premio(
    uid: int,
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Ativa Premium (por N dias) ou Vitalício para um usuário, gratuitamente.

    body: {
        tipo: "premium" | "vitalicio",
        dias: int (obrigatório se tipo=premium; ignorado se vitalicio)
    }
    """
    _require_admin(user_id)
    from datetime import timedelta

    tipo = body.get("tipo", "")
    user = conn.execute("SELECT id, plano, plano_expira FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    if tipo == "vitalicio":
        conn.execute(
            "UPDATE users SET plano = 'ilimitado', plano_expira = 'vitalicio' WHERE id = ?",
            (uid,)
        )
        conn.commit()
        log.info(f"[admin] Vitalício ativado como prêmio: user={uid}")
        return {"ok": True, "plano": "ilimitado", "expira": "vitalicio"}

    elif tipo == "premium":
        dias = body.get("dias", 30)
        try:
            dias = int(dias)
            if dias < 1:
                raise ValueError()
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="dias deve ser inteiro positivo")

        # Estender se já tem premium ativo, senão partir de agora
        plano_atual = user["plano"] or "free"
        plano_expira = user["plano_expira"] or ""
        base = datetime.now()
        if plano_atual == "premium" and plano_expira and plano_expira not in ("vitalicio", "vitalício", "lifetime"):
            try:
                exp = datetime.fromisoformat(plano_expira)
                if exp > base:
                    base = exp
            except (ValueError, TypeError):
                pass
        nova_expira = (base + timedelta(days=dias)).isoformat()

        conn.execute(
            "UPDATE users SET plano = 'premium', plano_expira = ? WHERE id = ?",
            (nova_expira, uid)
        )
        conn.commit()
        log.info(f"[admin] Premium {dias}d ativado como prêmio: user={uid} expira={nova_expira}")
        return {"ok": True, "plano": "premium", "expira": nova_expira, "dias": dias}

    else:
        raise HTTPException(status_code=400, detail="tipo deve ser 'premium' ou 'vitalicio'")

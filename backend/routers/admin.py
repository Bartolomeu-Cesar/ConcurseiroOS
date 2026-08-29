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


def _validade_plano(plano: str, plano_expira: str) -> dict:
    """Calcula o status de validade do plano de um usuário.

    Retorna: {situacao, dias_restantes, expira_em, label}
    - situacao: 'vitalicio' | 'ativo' | 'expira_em_breve' | 'expirado' | 'sem_plano'
    """
    from datetime import datetime, timezone

    if plano in ("free", "guest") or not plano:
        return {"situacao": "sem_plano", "dias_restantes": None, "expira_em": "", "label": "—"}

    exp = (plano_expira or "").strip()
    # Vitalício: ilimitado, ou premium com marcador vitalício, ou premium sem data
    if plano == "ilimitado" or exp.lower() in ("vitalicio", "vitalício", "lifetime"):
        return {"situacao": "vitalicio", "dias_restantes": None, "expira_em": "", "label": "♾️ Vitalício"}
    if plano == "premium" and not exp:
        return {"situacao": "vitalicio", "dias_restantes": None, "expira_em": "", "label": "♾️ Vitalício"}

    # Premium com data de expiração
    try:
        dt = datetime.fromisoformat(exp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return {"situacao": "ativo", "dias_restantes": None, "expira_em": exp, "label": "Ativo"}

    agora = datetime.now(timezone.utc)
    delta_dias = (dt - agora).days
    expira_fmt = dt.strftime("%d/%m/%Y")

    if delta_dias < 0:
        return {"situacao": "expirado", "dias_restantes": delta_dias, "expira_em": expira_fmt,
                "label": f"❌ Expirado em {expira_fmt}"}
    elif delta_dias <= 7:
        return {"situacao": "expira_em_breve", "dias_restantes": delta_dias, "expira_em": expira_fmt,
                "label": f"⚠️ {delta_dias}d restantes (até {expira_fmt})"}
    else:
        return {"situacao": "ativo", "dias_restantes": delta_dias, "expira_em": expira_fmt,
                "label": f"✅ {delta_dias}d restantes (até {expira_fmt})"}


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
            "validade": _validade_plano(r["plano"], r["plano_expira"]),
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
        "validade": _validade_plano(user["plano"], user["plano_expira"]),
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


# ============================================================
# COMPARTILHAMENTO DE RECURSOS ENTRE USUÁRIOS
# ============================================================

# Recursos suportados e como resetar progresso/SRS ao copiar para o destino.
# Cada recurso copia as linhas do user origem, atribuindo user_id do destino.
_RECURSOS_COMPARTILHAVEIS = {"pdfs", "questoes", "flashcards", "sumulas", "cadernos", "editais", "vademecum", "planejador"}


def _tabela_colunas(conn, tabela: str) -> list:
    """Retorna a lista de colunas de uma tabela."""
    return [r[1] for r in conn.execute(f"PRAGMA table_info({tabela})").fetchall()]


def _copiar_linhas(conn, tabela: str, origem_uid: int, destino_uid: int, resets: dict) -> int:
    """Copia todas as linhas de `tabela` do user origem para o destino.

    - Ignora a coluna 'id' (auto-increment gera novo).
    - Define user_id = destino_uid.
    - Aplica valores de `resets` (ex: proxima_revisao=hoje, repetitions=0).
    Retorna a quantidade de linhas copiadas.
    """
    cols = _tabela_colunas(conn, tabela)
    if "user_id" not in cols:
        return 0

    # Colunas a inserir (todas menos 'id')
    insert_cols = [c for c in cols if c != "id"]
    rows = conn.execute(f"SELECT {', '.join(insert_cols)} FROM {tabela} WHERE user_id = ?", (origem_uid,)).fetchall()

    copiadas = 0
    placeholders = ", ".join("?" for _ in insert_cols)
    for row in rows:
        valores = []
        for c in insert_cols:
            if c == "user_id":
                valores.append(destino_uid)
            elif c in resets:
                valores.append(resets[c])
            else:
                valores.append(row[c])
        conn.execute(f"INSERT INTO {tabela} ({', '.join(insert_cols)}) VALUES ({placeholders})", valores)
        copiadas += 1
    return copiadas


def _copiar_cadernos(conn, origem_uid: int, destino_uid: int) -> int:
    """Copia cadernos e suas questões associadas, mapeando questao_id copiadas.

    Requer que as questões já tenham sido copiadas nesta mesma operação — mas
    para robustez, copia também as questões referenciadas se ainda não existirem
    no destino (por conteúdo). Aqui usamos uma cópia independente: cria novas
    questões para o caderno e as associa.
    """
    from utils import today_str
    now = today_str()

    caderno_cols = _tabela_colunas(conn, "cadernos")
    cadernos = conn.execute("SELECT * FROM cadernos WHERE user_id = ?", (origem_uid,)).fetchall()
    total = 0

    tem_cadernos_questoes = bool(conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='cadernos_questoes'"
    ).fetchone())

    q_cols = _tabela_colunas(conn, "questoes")
    q_insert_cols = [c for c in q_cols if c != "id"]

    for cad in cadernos:
        # Criar novo caderno para o destino
        insert_cols = [c for c in caderno_cols if c != "id"]
        valores = []
        for c in insert_cols:
            valores.append(destino_uid if c == "user_id" else cad[c])
        placeholders = ", ".join("?" for _ in insert_cols)
        cur = conn.execute(f"INSERT INTO cadernos ({', '.join(insert_cols)}) VALUES ({placeholders})", valores)
        novo_caderno_id = cur.lastrowid
        total += 1

        if not tem_cadernos_questoes:
            continue

        # Copiar questões do caderno como novas questões do destino
        assoc = conn.execute(
            "SELECT questao_id, ordem FROM cadernos_questoes WHERE caderno_id = ?", (cad["id"],)
        ).fetchall()
        for a in assoc:
            q = conn.execute("SELECT * FROM questoes WHERE id = ?", (a["questao_id"],)).fetchone()
            if not q:
                continue
            qvals = []
            for c in q_insert_cols:
                qvals.append(destino_uid if c == "user_id" else q[c])
            qph = ", ".join("?" for _ in q_insert_cols)
            qcur = conn.execute(f"INSERT INTO questoes ({', '.join(q_insert_cols)}) VALUES ({qph})", qvals)
            nova_questao_id = qcur.lastrowid
            conn.execute(
                "INSERT INTO cadernos_questoes (caderno_id, questao_id, ordem, added_at) VALUES (?, ?, ?, ?)",
                (novo_caderno_id, nova_questao_id, a["ordem"], now)
            )
    return total


def _copiar_editais(conn, origem_uid: int, destino_uid: int) -> int:
    """Copia editais verticalizados (edital), dados do concurso (edital_info),
    resumos e notas de tópico, resetando o progresso de estudo do destino.

    Mapeia o id antigo→novo de cada tópico do edital para reconstruir os
    vínculos de resumos/notas (que referenciam edital_id).
    Retorna o número de tópicos de edital copiados.
    """
    from utils import today_str
    now = today_str()

    edital_cols = _tabela_colunas(conn, "edital")
    if "user_id" not in edital_cols:
        return 0
    insert_cols = [c for c in edital_cols if c != "id"]

    # Resets de progresso/SRS/mastery ao copiar
    resets = {
        "status": "Não Iniciado", "horas_estudadas": 0,
        "proxima_revisao": "", "intervalo_revisao": 0,
        "easiness_factor_edital": 2.5, "repetitions_edital": 0,
        "stability_edital": 0, "difficulty_edital": 0, "fsrs_state_edital": 0,
        "mastery_level": 0, "mastery_updated_at": "", "arquivado": 0,
    }
    # Filtrar resets para colunas que existem
    resets = {k: v for k, v in resets.items() if k in insert_cols}

    rows = conn.execute(f"SELECT * FROM edital WHERE user_id = ?", (origem_uid,)).fetchall()
    id_map = {}  # edital_id antigo → novo
    placeholders = ", ".join("?" for _ in insert_cols)
    for row in rows:
        valores = []
        for c in insert_cols:
            if c == "user_id":
                valores.append(destino_uid)
            elif c in resets:
                valores.append(resets[c])
            else:
                valores.append(row[c])
        cur = conn.execute(f"INSERT INTO edital ({', '.join(insert_cols)}) VALUES ({placeholders})", valores)
        id_map[row["id"]] = cur.lastrowid

    # edital_info (dados do concurso) — cópia direta
    try:
        _copiar_linhas(conn, "edital_info", origem_uid, destino_uid, {})
    except Exception:
        pass

    # resumos e notas_topico referenciam edital_id → remapear
    for tabela in ("resumos", "notas_topico"):
        try:
            cols = _tabela_colunas(conn, tabela)
            if "user_id" not in cols or "edital_id" not in cols:
                continue
            icols = [c for c in cols if c != "id"]
            deps = conn.execute(f"SELECT * FROM {tabela} WHERE user_id = ?", (origem_uid,)).fetchall()
            ph = ", ".join("?" for _ in icols)
            for d in deps:
                novo_edital_id = id_map.get(d["edital_id"])
                if not novo_edital_id:
                    continue
                vals = []
                for c in icols:
                    if c == "user_id":
                        vals.append(destino_uid)
                    elif c == "edital_id":
                        vals.append(novo_edital_id)
                    elif c == "created_at":
                        vals.append(now)
                    else:
                        vals.append(d[c])
                conn.execute(f"INSERT INTO {tabela} ({', '.join(icols)}) VALUES ({ph})", vals)
        except Exception:
            pass

    return len(rows)


def _copiar_vademecum(conn, origem_uid: int, destino_uid: int) -> int:
    """Copia leis do vade mécum (vademecum_leis) e seus artigos (vademecum_artigos),
    mapeando lei_id antigo→novo. Retorna o número de leis copiadas.
    """
    try:
        lei_cols = _tabela_colunas(conn, "vademecum_leis")
    except Exception:
        return 0
    if "user_id" not in lei_cols:
        return 0

    lei_icols = [c for c in lei_cols if c != "id"]
    leis = conn.execute("SELECT * FROM vademecum_leis WHERE user_id = ?", (origem_uid,)).fetchall()
    id_map = {}
    ph = ", ".join("?" for _ in lei_icols)
    for lei in leis:
        vals = [destino_uid if c == "user_id" else lei[c] for c in lei_icols]
        cur = conn.execute(f"INSERT INTO vademecum_leis ({', '.join(lei_icols)}) VALUES ({ph})", vals)
        id_map[lei["id"]] = cur.lastrowid

    # Artigos
    try:
        art_cols = _tabela_colunas(conn, "vademecum_artigos")
        if "lei_id" in art_cols:
            art_icols = [c for c in art_cols if c != "id"]
            aph = ", ".join("?" for _ in art_icols)
            for lei_antiga, lei_nova in id_map.items():
                artigos = conn.execute("SELECT * FROM vademecum_artigos WHERE lei_id = ?", (lei_antiga,)).fetchall()
                for art in artigos:
                    vals = []
                    for c in art_icols:
                        if c == "user_id":
                            vals.append(destino_uid)
                        elif c == "lei_id":
                            vals.append(lei_nova)
                        elif c == "destacado":
                            vals.append(0)
                        elif c == "anotacao":
                            vals.append("")
                        else:
                            vals.append(art[c])
                    conn.execute(f"INSERT INTO vademecum_artigos ({', '.join(art_icols)}) VALUES ({aph})", vals)
    except Exception:
        pass

    return len(leis)


def _contar_recursos(conn, uid: int) -> dict:
    """Conta os recursos compartilháveis de um usuário."""
    def _count(tabela, where="user_id = ?"):
        try:
            return conn.execute(f"SELECT COUNT(*) FROM {tabela} WHERE {where}", (uid,)).fetchone()[0]
        except Exception:
            return 0
    # Editais: contar por edital_nome distinto (não por tópico)
    try:
        editais = conn.execute(
            "SELECT COUNT(DISTINCT edital_nome) FROM edital WHERE user_id = ?", (uid,)
        ).fetchone()[0]
    except Exception:
        editais = 0
    return {
        "pdfs": _count("progress"),
        "questoes": _count("questoes"),
        "flashcards": _count("flashcards"),
        "sumulas": _count("sumulas"),
        "cadernos": _count("cadernos"),
        "editais": editais,
        "vademecum": _count("vademecum_leis"),
        "planejador": _count("planejador_semanal") + _count("calendario_personalizado"),
    }


@router.get("/users/{uid}/recursos", summary="Contagem de recursos de um usuário")
def contar_recursos_usuario(uid: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna quantos PDFs, questões, flashcards, súmulas e cadernos o usuário possui."""
    _require_admin(user_id)
    user = conn.execute("SELECT id, nome, email FROM users WHERE id = ?", (uid,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    return {"user": dict(user), "recursos": _contar_recursos(conn, uid)}


@router.post("/compartilhar", summary="Copiar recursos de um usuário para outro(s)")
def compartilhar_recursos(
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Copia recursos de um usuário de origem para um ou mais usuários de destino.

    body: {
        origem_uid: int,
        destino_uids: [int, ...],
        recursos: ["pdfs", "questoes", "flashcards", "sumulas", "cadernos"]
    }

    A cópia é independente: cada destino recebe uma cópia própria (pode editar
    sem afetar a origem). Progresso de leitura e SRS são resetados no destino.
    """
    _require_admin(user_id)
    from utils import today_str

    origem_uid = body.get("origem_uid")
    destino_uids = body.get("destino_uids", [])
    recursos = body.get("recursos", [])

    if not origem_uid:
        raise HTTPException(status_code=400, detail="origem_uid é obrigatório.")
    if not destino_uids or not isinstance(destino_uids, list):
        raise HTTPException(status_code=400, detail="destino_uids deve ser lista não-vazia.")
    if not recursos or not isinstance(recursos, list):
        raise HTTPException(status_code=400, detail="recursos deve ser lista não-vazia.")

    recursos_invalidos = set(recursos) - _RECURSOS_COMPARTILHAVEIS
    if recursos_invalidos:
        raise HTTPException(status_code=400, detail=f"Recursos inválidos: {list(recursos_invalidos)}. Válidos: {list(_RECURSOS_COMPARTILHAVEIS)}")

    # Validar origem
    origem = conn.execute("SELECT id FROM users WHERE id = ?", (origem_uid,)).fetchone()
    if not origem:
        raise HTTPException(status_code=404, detail="Usuário de origem não encontrado.")

    hoje = today_str()
    resultado = {}

    for destino_uid in destino_uids:
        if destino_uid == origem_uid:
            resultado[str(destino_uid)] = {"erro": "Origem e destino são o mesmo usuário."}
            continue
        destino = conn.execute("SELECT id FROM users WHERE id = ?", (destino_uid,)).fetchone()
        if not destino:
            resultado[str(destino_uid)] = {"erro": "Usuário destino não encontrado."}
            continue

        copiados = {}

        if "questoes" in recursos:
            copiados["questoes"] = _copiar_linhas(conn, "questoes", origem_uid, destino_uid, {})
        if "flashcards" in recursos:
            copiados["flashcards"] = _copiar_linhas(conn, "flashcards", origem_uid, destino_uid, {
                "proxima_revisao": hoje, "intervalo_dias": 1, "easiness_factor": 2.5,
                "repetitions": 0, "stability": 0, "difficulty": 0, "fsrs_state": 0,
            })
        if "sumulas" in recursos:
            copiados["sumulas"] = _copiar_linhas(conn, "sumulas", origem_uid, destino_uid, {
                "proxima_revisao": hoje, "intervalo_dias": 1, "easiness_factor": 2.5,
                "repetitions": 0, "stability": 0, "difficulty_sumulas": 0, "fsrs_state": 0,
            })
        if "pdfs" in recursos:
            copiados["pdfs"] = _copiar_linhas(conn, "progress", origem_uid, destino_uid, {
                "current_page": 1, "last_read_at": "",
            })
        if "cadernos" in recursos:
            copiados["cadernos"] = _copiar_cadernos(conn, origem_uid, destino_uid)
        if "editais" in recursos:
            copiados["editais"] = _copiar_editais(conn, origem_uid, destino_uid)
        if "vademecum" in recursos:
            copiados["vademecum"] = _copiar_vademecum(conn, origem_uid, destino_uid)
        if "planejador" in recursos:
            p1 = _copiar_linhas(conn, "planejador_semanal", origem_uid, destino_uid, {})
            p2 = _copiar_linhas(conn, "calendario_personalizado", origem_uid, destino_uid, {})
            copiados["planejador"] = p1 + p2

        resultado[str(destino_uid)] = {"copiados": copiados}

    conn.commit()
    log.info(f"[admin] Compartilhamento: origem={origem_uid} destinos={destino_uids} recursos={recursos}")
    return {"ok": True, "origem_uid": origem_uid, "resultado": resultado}

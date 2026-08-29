"""Calendário personalizado: CRUD, atividades concluídas, streak."""
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends

from database import get_db_session
from deps import get_user_id
from logger import log
from sanitize import sanitize_input
from schemas import CalendarioItem, AtividadeConcluidaRequest, DesmarcarAtividadeRequest
from utils import today_str

router = APIRouter(prefix="", tags=["Calendário"])

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

# ============================================================

@router.get("/api/calendario-personalizado")
def get_calendario_personalizado(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna o calendário personalizado salvo pelo usuário."""
    rows = conn.execute(
        "SELECT id, dia_semana, materia, topicos, tempo_min, tipo, ordem FROM calendario_personalizado WHERE user_id = ? ORDER BY dia_semana, ordem",
        (user_id,)
    ).fetchall()
    items = [dict(r) for r in rows]

    # Calculate actual dates for this week
    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())  # Monday

    dias = []
    for d in range(7):
        atividades = [i for i in items if i["dia_semana"] == d]
        tempo_total = sum(a["tempo_min"] for a in atividades)
        materias = list(set(a["materia"] for a in atividades if a["materia"]))
        dia_data = (inicio_semana + timedelta(days=d)).isoformat()
        dias.append({
            "dia_semana": d, "nome": NOMES_DIAS[d], "data": dia_data,
            "atividades": atividades, "tempo_total_min": tempo_total, "materias": materias
        })
    return {"dias": dias}


@router.post("/api/calendario-personalizado")
def add_calendario_item(body: CalendarioItem, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.dia_semana, sanitize_input(body.materia), sanitize_input(body.topicos, max_length=2000),
         body.tempo_min, sanitize_input(body.tipo), body.ordem, user_id)
    )
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/calendario-personalizado/{id}")
def delete_calendario_item(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM calendario_personalizado WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


@router.delete("/api/calendario-personalizado")
def clear_calendario_personalizado(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM calendario_personalizado WHERE user_id = ?", (user_id,))
    conn.commit()
    return {"ok": True}


@router.post("/api/calendario-personalizado/salvar-completo")
def salvar_calendario_completo(dias: list = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Salva o calendário completo (limpa e recria)."""
    conn.execute("DELETE FROM calendario_personalizado WHERE user_id = ?", (user_id,))
    count = 0
    for item in dias:
        conn.execute(
            "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.get("dia_semana", 0), sanitize_input(item.get("materia", "")),
             sanitize_input(item.get("topicos", ""), max_length=2000),
             item.get("tempo_min", 60), sanitize_input(item.get("tipo", "estudo")), item.get("ordem", count), user_id)
        )
        count += 1
    conn.commit()
    return {"ok": True, "salvos": count}


# ============================================================
# ATIVIDADES DO CALENDÁRIO - CONCLUSÃO + STREAK
# ============================================================

@router.post("/api/calendario/atividade-concluida")
def marcar_atividade_concluida(body: AtividadeConcluidaRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Marca uma atividade do calendário como concluída."""
    data_str = body.data or today_str()
    dia_semana = body.dia_semana
    materia = sanitize_input(body.materia)
    tipo = sanitize_input(body.tipo)
    tempo_min = body.tempo_min

    conn.execute("""
        INSERT INTO calendario_atividades (data, dia_semana, materia, tipo, tempo_min, concluida, concluida_at, user_id)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    """, (data_str, dia_semana, materia, tipo, tempo_min, datetime.now().isoformat(), user_id))

    _update_calendario_streak(conn, data_str, body.total_atividades, user_id)

    # Se for atividade da Trilha, conclui automaticamente a etapa correspondente
    # (marca o tópico do edital como Concluído e desbloqueia a próxima etapa).
    trilha_concluida = False
    if tipo == "trilha":
        try:
            from routers.trilha import marcar_etapa_por_topico
            trilha_concluida = marcar_etapa_por_topico(
                conn, user_id, materia, sanitize_input(body.topico)
            )
        except Exception as e:  # pragma: no cover - defensivo
            log.warning(f"Falha ao concluir etapa da trilha via calendário: {e}")

    conn.commit()
    log.info(f"Atividade concluída: {materia} ({tipo}) em {data_str}")
    return {"ok": True, "trilha_etapa_concluida": trilha_concluida}


@router.delete("/api/calendario/atividade-concluida")
def desmarcar_atividade_concluida(body: DesmarcarAtividadeRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Desmarca uma atividade (desfaz conclusão)."""
    data_str = body.data or today_str()
    materia = sanitize_input(body.materia)
    tipo = sanitize_input(body.tipo)

    conn.execute("""
        DELETE FROM calendario_atividades
        WHERE data = ? AND materia = ? AND tipo = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
    """, (data_str, materia, tipo, user_id))

    _update_calendario_streak(conn, data_str, body.total_atividades, user_id)
    conn.commit()
    return {"ok": True}


@router.get("/api/calendario/concluidas")
def get_atividades_concluidas(data: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna atividades concluídas de um dia (ou hoje)."""
    data_str = data or today_str()
    rows = conn.execute(
        "SELECT * FROM calendario_atividades WHERE data = ? AND concluida = 1 AND user_id = ?", (data_str, user_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/calendario/streak")
def get_calendario_streak(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna streak de dias com 100% do calendário concluído."""
    rows = conn.execute("""
        SELECT data, pct_conclusao FROM calendario_streaks
        WHERE pct_conclusao >= 100 AND user_id = ? ORDER BY data DESC
    """, (user_id,)).fetchall()

    streak = 0
    hoje = date.today()
    for i, r in enumerate(rows):
        expected = (hoje - timedelta(days=i)).isoformat()
        if r[0] == expected:
            streak += 1
        else:
            break

    best = 0
    current = 0
    all_dates = sorted([r[0] for r in rows])
    for i, d in enumerate(all_dates):
        if i == 0:
            current = 1
        else:
            prev = date.fromisoformat(all_dates[i-1])
            curr = date.fromisoformat(d)
            if (curr - prev).days == 1:
                current += 1
            else:
                current = 1
        best = max(best, current)

    hoje_row = conn.execute("SELECT * FROM calendario_streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    return {
        "streak_calendario": streak,
        "melhor_streak_calendario": best,
        "hoje": dict(hoje_row) if hoje_row else {"total_atividades": 0, "concluidas": 0, "pct_conclusao": 0}
    }


def _update_calendario_streak(conn, data_str: str, total_atividades: int = 0, user_id: int = 0):
    """Atualiza o registro de streak do calendário para uma data."""
    concluidas = conn.execute(
        "SELECT COUNT(*) FROM calendario_atividades WHERE data = ? AND concluida = 1 AND user_id = ?", (data_str, user_id)
    ).fetchone()[0]
    pct = round((concluidas / total_atividades * 100) if total_atividades > 0 else 0, 1)
    xp = 50 if pct >= 100 else 0

    conn.execute("""
        INSERT INTO calendario_streaks (data, total_atividades, concluidas, pct_conclusao, xp_bonus, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(data) DO UPDATE SET
            total_atividades = ?, concluidas = ?, pct_conclusao = ?, xp_bonus = ?
    """, (data_str, total_atividades, concluidas, pct, xp, user_id,
          total_atividades, concluidas, pct, xp))



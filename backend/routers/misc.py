"""Router de utilidades gerais (health, backup, busca, notificações, etc.)."""
import random
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from backup import create_backup, list_backups, restore_backup
from database import get_db_session, rebuild_search_index
from deps import get_user_id, get_authenticated_user_id
from logger import log
from models import HealthResponse, OkResponse
from settings import settings
from utils import today_str

router = APIRouter(prefix="", tags=["Utilidades"])

# Set from main.py
APP_START_TIME = None
DB_PATH = "./progress.db"


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/api/health", response_model=HealthResponse, summary="Health Check")
def health_check(conn=Depends(get_db_session)):
    """Retorna status do sistema, uptime, estado do banco de dados e métricas."""
    db_status = "connected"
    tables_count = 0
    edital_count = 0

    try:
        conn.execute("SELECT 1")
        tables_count = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
        edital_count = conn.execute("SELECT COUNT(*) FROM edital").fetchone()[0]
    except Exception as e:
        db_status = "error"
        log.error(f"Health check DB error: {e}")

    uptime = time.time() - APP_START_TIME if APP_START_TIME else 0

    return {
        "status": "ok",
        "uptime_seconds": round(uptime, 1),
        "database": db_status,
        "version": settings.APP_VERSION,
        "tables_count": tables_count,
        "edital_count": edital_count,
        "timestamp": datetime.now().isoformat()
    }


# ============================================================
# BACKUP ENDPOINTS (admin only: user_id=1)
# ============================================================

class RestoreRequest(BaseModel):
    filename: str


@router.get("/api/backups", summary="Listar backups")
def get_backups(user_id: int = Depends(get_user_id)):
    if user_id != 1:
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    return list_backups()


@router.post("/api/backups", summary="Criar backup")
def create_backup_endpoint(user_id: int = Depends(get_user_id)):
    if user_id != 1:
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    # TODO: file size check (10MB max) placeholder
    path = create_backup(DB_PATH)
    log.info(f"Manual backup created: {path}")
    return {"ok": True, "path": path}


@router.post("/api/backups/restore", summary="Restaurar backup")
def restore_backup_endpoint(body: RestoreRequest, user_id: int = Depends(get_user_id)):
    if user_id != 1:
        raise HTTPException(status_code=403, detail="Acesso restrito ao administrador")
    success = restore_backup(body.filename, DB_PATH)
    if not success:
        raise HTTPException(status_code=404, detail="Backup não encontrado")
    log.info(f"Backup restored: {body.filename}")
    return {"ok": True, "restored": body.filename}


# ============================================================
# BUSCA GLOBAL (FTS5)
# ============================================================

@router.get("/api/search", summary="Busca global")
def global_search(q: str = Query(..., min_length=1), conn=Depends(get_db_session)):
    try:
        rows = conn.execute("""
            SELECT source, source_id, title,
                   snippet(search_index, 3, '<b>', '</b>', '...', 32) as snippet, rank
            FROM search_index WHERE search_index MATCH ?
            ORDER BY rank LIMIT 50
        """, (q,)).fetchall()
    except Exception:
        try:
            rows = conn.execute("""
                SELECT source, source_id, title,
                       snippet(search_index, 3, '<b>', '</b>', '...', 32) as snippet, rank
                FROM search_index WHERE search_index MATCH ?
                ORDER BY rank LIMIT 50
            """, (f'"{q}"',)).fetchall()
        except Exception:
            return []

    return [{"source": r[0], "source_id": int(r[1]) if r[1] else None,
             "title": r[2], "snippet": r[3], "rank": r[4]} for r in rows]


@router.post("/api/search/reindex", summary="Reindexar busca")
def reindex_search(conn=Depends(get_db_session)):
    rebuild_search_index(conn)
    log.info("Search index manually rebuilt")
    return {"ok": True, "message": "Índice reconstruído com sucesso"}


# ============================================================
# NOTIFICAÇÕES
# ============================================================

@router.get("/api/notificacoes")
def get_notificacoes(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna lembretes/notificações pendentes"""
    notifs = []

    # Flashcards pendentes
    flash_pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)
    ).fetchone()[0]
    if flash_pendentes > 0:
        notifs.append({
            "tipo": "flashcard", "icon": "🧠",
            "msg": f"Você tem {flash_pendentes} flashcard(s) para revisar hoje!",
            "prioridade": "alta"
        })

    # Súmulas pendentes
    try:
        sumulas_pendentes = conn.execute(
            "SELECT COUNT(*) FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)
        ).fetchone()[0]
        if sumulas_pendentes > 0:
            notifs.append({
                "tipo": "sumula", "icon": "⚖️",
                "msg": f"Você tem {sumulas_pendentes} súmula(s) para revisar hoje!",
                "prioridade": "alta"
            })
    except Exception:
        pass

    # Metas não cumpridas
    config = conn.execute("SELECT meta_horas, meta_questoes, meta_flashcards FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    if config and hoje:
        horas_hoje = float(hoje["horas_estudadas"] or 0)
        questoes_hoje = int(hoje["questoes_resolvidas"] or 0)
        if horas_hoje < float(config["meta_horas"]):
            falta = float(config["meta_horas"]) - horas_hoje
            notifs.append({"tipo": "meta", "icon": "⏱", "msg": f"Faltam {falta:.1f}h para bater a meta de hoje", "prioridade": "media"})
        if questoes_hoje < int(config["meta_questoes"]):
            falta = int(config["meta_questoes"]) - questoes_hoje
            notifs.append({"tipo": "meta", "icon": "❓", "msg": f"Faltam {falta} questões para a meta de hoje", "prioridade": "media"})
    elif config:
        notifs.append({"tipo": "meta", "icon": "📖", "msg": "Você ainda não estudou hoje! Que tal começar?", "prioridade": "alta"})

    # Streak em risco
    ontem = (date.today() - timedelta(days=1)).isoformat()
    streak_ontem = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (ontem, user_id)).fetchone()
    if not hoje and streak_ontem:
        notifs.append({"tipo": "streak", "icon": "🔥", "msg": "Seu streak está em risco! Estude hoje para não perder.", "prioridade": "alta"})

    return notifs


# ============================================================
# COUNTDOWN
# ============================================================

@router.get("/api/countdown")
def get_countdown(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    try:
        rows = conn.execute("""
            SELECT edital_nome, cargo, data_prova_objetiva, data_prova_discursiva, local_prova
            FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?
            ORDER BY data_prova_objetiva
        """, (user_id,)).fetchall()
    except Exception:
        rows = []
    return [{"edital": r[0], "cargo": r[1], "data_objetiva": r[2],
             "data_discursiva": r[3], "local": r[4]} for r in rows]


# ============================================================
# MODO FOCO
# ============================================================

@router.get("/api/modo-foco/status")
def get_modo_foco():
    return {"disponivel": True, "dica": "Use F11 para tela cheia + o botão Modo Foco na interface"}


# ============================================================
# ESTUDO ALEATÓRIO
# ============================================================

@router.get("/api/estudo/aleatorio")
def topico_aleatorio(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT id, edital_nome, cargo, materia, topico FROM edital WHERE status != 'Concluído' AND user_id = ?"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    rows = conn.execute(query, params).fetchall()
    if not rows:
        return {"message": "Todos os tópicos foram concluídos! 🎉"}
    chosen = random.choice(rows)
    return dict(chosen)


# ============================================================
# REGISTRAR SESSÃO DE ESTUDO
# ============================================================

class SessaoEstudoRegistrar(BaseModel):
    horas: float
    materia: str = "Leitura PDF"
    tipo: str = "timer"


@router.post("/api/sessoes-estudo/registrar", summary="Registrar sessão de estudo")
def registrar_sessao_estudo(body: SessaoEstudoRegistrar, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if body.horas <= 0:
        return {"ok": False, "message": "Tempo inválido"}
    from datetime import datetime
    now_iso = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (body.materia, body.horas, today_str(), body.tipo, user_id, now_iso)
    )
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas, user_id) VALUES (?, ?, ?)
        ON CONFLICT(data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, user_id, body.horas))
    conn.commit()
    log.info(f"Session registered: {body.horas:.2f}h ({body.materia})")
    return {"ok": True, "horas": body.horas}


# ============================================================
# CONQUISTAS DIÁRIAS (DAILY CHALLENGE)
# ============================================================

@router.get("/api/daily-challenge")
def daily_challenge(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna uma questão aleatória como desafio do dia"""
    row = conn.execute("SELECT * FROM questoes WHERE user_id = ? ORDER BY RANDOM() LIMIT 1", (user_id,)).fetchone()
    if not row:
        return {"message": "Nenhuma questão disponível para o desafio do dia"}
    return dict(row)


@router.get("/api/conquistas-diarias")
def conquistas_diarias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna missões diárias auto-geradas"""
    missoes = []
    config = conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()

    horas_hoje = hoje["horas_estudadas"] if hoje else 0
    questoes_hoje = hoje["questoes_resolvidas"] if hoje else 0
    flash_hoje = hoje["flashcards_revisados"] if hoje else 0

    missoes.append({
        "titulo": "📖 Estudar por 1 hora",
        "progresso": min(horas_hoje, 1.0),
        "meta": 1.0,
        "concluida": horas_hoje >= 1.0,
        "xp": 50
    })
    missoes.append({
        "titulo": "❓ Resolver 10 questões",
        "progresso": min(questoes_hoje, 10),
        "meta": 10,
        "concluida": questoes_hoje >= 10,
        "xp": 30
    })
    missoes.append({
        "titulo": "🧠 Revisar 5 flashcards",
        "progresso": min(flash_hoje, 5),
        "meta": 5,
        "concluida": flash_hoje >= 5,
        "xp": 20
    })

    # Missão bônus: speed review
    flash_pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)
    ).fetchone()[0]
    if flash_pendentes >= 10:
        missoes.append({
            "titulo": "⚡ Speed Review (20 flashcards rápidos)",
            "progresso": 0,
            "meta": 1,
            "concluida": False,
            "xp": 40
        })

    return missoes


@router.get("/api/intercalacao")
def intercalacao(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna sugestão de intercalação: matérias diferentes para alternar"""
    materias = conn.execute("""
        SELECT DISTINCT materia FROM edital WHERE status != 'Concluído' AND user_id = ? ORDER BY RANDOM() LIMIT 3
    """, (user_id,)).fetchall()
    return [{"materia": r[0], "acao": "Estudar por 25 minutos (Pomodoro)"} for r in materias]


@router.get("/api/speed-review")
def speed_review(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna 20 flashcards aleatórios para speed review"""
    from constants import SPEED_REVIEW_LIMIT
    rows = conn.execute(
        "SELECT id, pergunta, resposta FROM flashcards WHERE user_id = ? ORDER BY RANDOM() LIMIT ?",
        (user_id, SPEED_REVIEW_LIMIT)
    ).fetchall()
    return [dict(r) for r in rows]

import random
import time
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from database import get_db, rebuild_search_index
from logger import log
from models import (
    NotaCreate, PlanejadorItem, CadernoCreate, CadernoAddItem,
    BookmarkCreate, FeynmanCreate
)
from utils import today_str
from backup import create_backup, list_backups, restore_backup

router = APIRouter(prefix="", tags=["Utilidades"])

# Set from main.py
APP_START_TIME = None
DB_PATH = "./progress.db"


# ============================================================
# HEALTH CHECK
# ============================================================

@router.get("/api/health", summary="Health Check", description="Verifica o status da aplicação, conexão com banco e métricas básicas")
def health_check():
    """Retorna status do sistema, uptime, estado do banco de dados e métricas."""
    db_status = "connected"
    tables_count = 0
    edital_count = 0

    try:
        with get_db() as conn:
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
        "version": "2.1.0",
        "tables_count": tables_count,
        "edital_count": edital_count,
        "timestamp": datetime.now().isoformat()
    }


# ============================================================
# BACKUP ENDPOINTS
# ============================================================

class RestoreRequest(BaseModel):
    filename: str


@router.get("/api/backups", summary="Listar backups", description="Lista todos os backups disponíveis com tamanho e data de criação")
def get_backups():
    """Lista backups disponíveis."""
    return list_backups()


@router.post("/api/backups", summary="Criar backup", description="Cria um backup manual do banco de dados")
def create_backup_endpoint():
    """Cria backup manual do banco de dados."""
    path = create_backup(DB_PATH)
    log.info(f"Manual backup created: {path}")
    return {"ok": True, "path": path}


@router.post("/api/backups/restore", summary="Restaurar backup", description="Restaura o banco de dados a partir de um backup específico")
def restore_backup_endpoint(body: RestoreRequest):
    """Restaura um backup específico."""
    success = restore_backup(body.filename, DB_PATH)
    if not success:
        raise HTTPException(404, "Backup não encontrado")
    log.info(f"Backup restored: {body.filename}")
    return {"ok": True, "restored": body.filename}


# ============================================================
# BUSCA GLOBAL (FTS5)
# ============================================================

@router.get("/api/search", summary="Busca global", description="Busca full-text em todos os conteúdos (edital, questões, flashcards, notas)")
def global_search(q: str = Query(..., min_length=1)):
    """Busca full-text usando FTS5 em todos os conteúdos indexados."""
    with get_db() as conn:
        try:
            rows = conn.execute("""
                SELECT source, source_id, title,
                       snippet(search_index, 3, '<b>', '</b>', '...', 32) as snippet,
                       rank
                FROM search_index
                WHERE search_index MATCH ?
                ORDER BY rank
                LIMIT 50
            """, (q,)).fetchall()
        except Exception as e:
            log.error(f"Search error: {e}")
            # Fallback: try with quoted query
            try:
                rows = conn.execute("""
                    SELECT source, source_id, title,
                           snippet(search_index, 3, '<b>', '</b>', '...', 32) as snippet,
                           rank
                    FROM search_index
                    WHERE search_index MATCH ?
                    ORDER BY rank
                    LIMIT 50
                """, (f'"{q}"',)).fetchall()
            except Exception:
                return []

    return [
        {
            "source": r[0],
            "source_id": int(r[1]) if r[1] else None,
            "title": r[2],
            "snippet": r[3],
            "rank": r[4]
        }
        for r in rows
    ]


@router.post("/api/search/reindex", summary="Reindexar busca", description="Reconstrói o índice de busca full-text com todos os dados atuais")
def reindex_search():
    """Reconstrói o índice de busca FTS5."""
    with get_db() as conn:
        rebuild_search_index(conn)
    log.info("Search index manually rebuilt")
    return {"ok": True, "message": "Índice reconstruído com sucesso"}


# ============================================================
# NOTIFICAÇÕES
# ============================================================

@router.get("/api/notificacoes")
def get_notificacoes():
    """Retorna lembretes/notificações pendentes"""
    with get_db() as conn:
        notifs = []

        # Flashcards pendentes
        flash_pendentes = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)
        ).fetchone()[0]
        if flash_pendentes > 0:
            notifs.append({
                "tipo": "flashcard",
                "icon": "🧠",
                "msg": f"Você tem {flash_pendentes} flashcard(s) para revisar hoje!",
                "prioridade": "alta"
            })

        # Metas não cumpridas
        config = conn.execute("SELECT meta_horas, meta_questoes, meta_flashcards FROM metas_config WHERE id = 1").fetchone()
        hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()
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
        streak_ontem = conn.execute("SELECT * FROM streaks WHERE data = ?", (ontem,)).fetchone()
        if not hoje and streak_ontem:
            notifs.append({"tipo": "streak", "icon": "🔥", "msg": "Seu streak está em risco! Estude hoje para não perder.", "prioridade": "alta"})

    return notifs


# ============================================================
# PLANEJADOR SEMANAL
# ============================================================

@router.get("/api/planejador")
def get_planejador():
    with get_db() as conn:
        rows = conn.execute("SELECT id, dia_semana, materia, horas FROM planejador_semanal ORDER BY dia_semana, id").fetchall()
    return [dict(r) for r in rows]


@router.post("/api/planejador")
def add_planejador(body: PlanejadorItem):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO planejador_semanal (dia_semana, materia, horas) VALUES (?, ?, ?)",
                           (body.dia_semana, body.materia, body.horas))
        conn.commit()
    log.info(f"Planejador item added: {body.materia} dia {body.dia_semana}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/planejador/{id}")
def delete_planejador(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM planejador_semanal WHERE id = ?", (id,))
        conn.commit()
    log.info(f"Planejador item deleted: {id}")
    return {"ok": True}


# ============================================================
# CADERNOS
# ============================================================

@router.get("/api/cadernos")
def list_cadernos():
    with get_db() as conn:
        cadernos = conn.execute("SELECT * FROM cadernos ORDER BY created_at DESC").fetchall()
        result = []
        for c in cadernos:
            count = conn.execute("SELECT COUNT(*) FROM caderno_itens WHERE caderno_id = ?", (c[0],)).fetchone()[0]
            d = dict(c)
            d["total_itens"] = count
            result.append(d)
    return result


@router.post("/api/cadernos")
def create_caderno(body: CadernoCreate):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO cadernos (nome, descricao, created_at) VALUES (?, ?, ?)",
                           (body.nome, body.descricao, datetime.now().isoformat()))
        conn.commit()
    log.info(f"Caderno created: {body.nome}")
    return {"id": cur.lastrowid, "ok": True}


@router.post("/api/cadernos/{id}/adicionar")
def add_to_caderno(id: int, body: CadernoAddItem):
    with get_db() as conn:
        conn.execute("INSERT INTO caderno_itens (caderno_id, tipo, item_id) VALUES (?, ?, ?)",
                     (id, body.tipo, body.item_id))
        conn.commit()
    return {"ok": True}


@router.get("/api/cadernos/{id}")
def get_caderno(id: int):
    with get_db() as conn:
        caderno = conn.execute("SELECT * FROM cadernos WHERE id = ?", (id,)).fetchone()
        if not caderno:
            raise HTTPException(404)
        itens = conn.execute("SELECT * FROM caderno_itens WHERE caderno_id = ?", (id,)).fetchall()
    return {"caderno": dict(caderno), "itens": [dict(i) for i in itens]}


@router.delete("/api/cadernos/{id}")
def delete_caderno(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM caderno_itens WHERE caderno_id = ?", (id,))
        conn.execute("DELETE FROM cadernos WHERE id = ?", (id,))
        conn.commit()
    log.info(f"Caderno deleted: {id}")
    return {"ok": True}


# ============================================================
# BOOKMARKS
# ============================================================

@router.get("/api/bookmarks/{path:path}")
def get_bookmarks(path: str):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM bookmarks_pdf WHERE pdf_path = ? ORDER BY pagina", (path,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/bookmarks")
def create_bookmark(body: BookmarkCreate):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO bookmarks_pdf (pdf_path, pagina, label, cor, created_at) VALUES (?, ?, ?, ?, ?)",
                           (body.pdf_path, body.pagina, body.label, body.cor, datetime.now().isoformat()))
        conn.commit()
    log.info(f"Bookmark created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/bookmarks/{id}")
def delete_bookmark(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM bookmarks_pdf WHERE id = ?", (id,))
        conn.commit()
    return {"ok": True}


# ============================================================
# FEYNMAN
# ============================================================

@router.get("/api/feynman/{edital_id}")
def get_feynman(edital_id: int):
    """Retorna explicações Feynman de um tópico"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM feynman WHERE edital_id = ? ORDER BY created_at DESC", (edital_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/feynman")
def create_feynman(body: FeynmanCreate):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO feynman (edital_id, explicacao, created_at) VALUES (?, ?, ?)",
                           (body.edital_id, body.explicacao, datetime.now().isoformat()))
        conn.commit()
    log.info(f"Feynman explanation added for edital_id={body.edital_id}")
    return {"id": cur.lastrowid, "ok": True}


# ============================================================
# NOTAS POR PDF
# ============================================================

@router.get("/api/notas/{path:path}")
def get_notas_pdf(path: str):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM notas_pdf WHERE pdf_path = ? ORDER BY pagina, id", (path,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/notas")
def create_nota(body: NotaCreate):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO notas_pdf (pdf_path, pagina, conteudo, created_at) VALUES (?, ?, ?, ?)",
                           (body.pdf_path, body.pagina, body.conteudo, datetime.now().isoformat()))
        conn.commit()
    log.info(f"Nota created: {body.pdf_path} p.{body.pagina}")
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas/{id}")
def delete_nota(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM notas_pdf WHERE id = ?", (id,))
        conn.commit()
    return {"ok": True}


# ============================================================
# MODO FOCO
# ============================================================

@router.get("/api/modo-foco/status")
def get_modo_foco():
    """Retorna status do modo foco (controlado pelo frontend)"""
    return {"disponivel": True, "dica": "Use F11 para tela cheia + o botão Modo Foco na interface"}


# ============================================================
# COUNTDOWN
# ============================================================

@router.get("/api/countdown")
def get_countdown():
    """Retorna countdowns para as próximas provas"""
    with get_db() as conn:
        try:
            rows = conn.execute("""
                SELECT edital_nome, cargo, data_prova_objetiva, data_prova_discursiva, local_prova
                FROM edital_info
                WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital'
                ORDER BY data_prova_objetiva
            """).fetchall()
        except Exception:
            rows = []
    result = []
    for r in rows:
        result.append({
            "edital": r[0],
            "cargo": r[1],
            "data_objetiva": r[2],
            "data_discursiva": r[3],
            "local": r[4]
        })
    return result


# ============================================================
# ESTUDO ALEATÓRIO
# ============================================================

@router.get("/api/estudo/aleatorio")
def topico_aleatorio(edital_nome: str = "", cargo: str = ""):
    """Sorteia um tópico aleatório não concluído para estudo"""
    with get_db() as conn:
        query = "SELECT id, edital_nome, cargo, materia, topico FROM edital WHERE status != 'Concluído'"
        params = []
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

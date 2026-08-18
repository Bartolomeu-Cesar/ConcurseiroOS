import random
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException

from database import get_db
from models import (
    NotaCreate, PlanejadorItem, CadernoCreate, CadernoAddItem,
    BookmarkCreate, FeynmanCreate
)
from utils import today_str

router = APIRouter()


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
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/planejador/{id}")
def delete_planejador(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM planejador_semanal WHERE id = ?", (id,))
        conn.commit()
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

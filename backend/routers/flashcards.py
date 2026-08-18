import math
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db
from logger import log
from models import FlashcardCreate, FlashcardReview
from utils import today_str

router = APIRouter(prefix="", tags=["Flashcards"])


@router.get("/api/flashcards", summary="Listar flashcards", description="Lista todos os flashcards com paginação opcional")
def list_flashcards(page: Optional[int] = Query(None), limit: int = 50):
    with get_db() as conn:
        rows = conn.execute("SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias FROM flashcards").fetchall()

    items = [dict(r) for r in rows]

    # Se page não fornecido, retorna array completo (retrocompatibilidade)
    if page is None:
        return items

    # Paginação
    total = len(items)
    pages = math.ceil(total / limit) if limit > 0 else 1
    start = (page - 1) * limit
    end = start + limit
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages
    }


@router.get("/api/flashcards/today")
def get_flashcards_today():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias FROM flashcards WHERE proxima_revisao <= ?",
            (today_str(),)
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/flashcards", summary="Criar flashcard", description="Cria um novo flashcard com revisão SRS")
def create_flashcard(body: FlashcardCreate):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, proxima_revisao) VALUES (?, ?, ?)",
            (body.pergunta, body.resposta, today_str())
        )
        conn.commit()
        new_id = cur.lastrowid
    log.info(f"Flashcard created: id={new_id}")
    return {"id": new_id, "pergunta": body.pergunta, "resposta": body.resposta,
            "proxima_revisao": today_str(), "intervalo_dias": 1}


@router.post("/api/flashcards/{id}/review")
def review_flashcard(id: int, body: FlashcardReview):
    with get_db() as conn:
        row = conn.execute("SELECT intervalo_dias FROM flashcards WHERE id = ?", (id,)).fetchone()
        if not row:
            raise HTTPException(404)
        new_intervalo = row[0] * 2 if body.acertou else 1
        proxima = (date.today() + timedelta(days=new_intervalo)).isoformat()
        conn.execute("UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ? WHERE id = ?",
                     (new_intervalo, proxima, id))
        # Atualizar streak
        conn.execute("""
            INSERT INTO streaks (data, flashcards_revisados) VALUES (?, 1)
            ON CONFLICT(data) DO UPDATE SET flashcards_revisados = flashcards_revisados + 1
        """, (today_str(),))
        conn.commit()
    return {"id": id, "intervalo_dias": new_intervalo, "proxima_revisao": proxima}


@router.delete("/api/flashcards/{id}")
def delete_flashcard(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM flashcards WHERE id = ?", (id,))
        conn.commit()
    log.info(f"Flashcard deleted: id={id}")
    return {"ok": True}


@router.get("/api/speed-review")
def speed_review():
    """Retorna 20 flashcards para revisão relâmpago (modo rápido)"""
    with get_db() as conn:
        rows = conn.execute("""
            SELECT id, pergunta, resposta FROM flashcards
            WHERE proxima_revisao <= ?
            ORDER BY intervalo_dias ASC
            LIMIT 20
        """, (today_str(),)).fetchall()
    return [{"id": r[0], "pergunta": r[1], "resposta": r[2]} for r in rows]

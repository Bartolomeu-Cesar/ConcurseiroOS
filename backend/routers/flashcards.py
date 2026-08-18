from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

from database import get_db
from models import FlashcardCreate, FlashcardReview
from utils import today_str

router = APIRouter()


@router.get("/api/flashcards")
def list_flashcards():
    with get_db() as conn:
        rows = conn.execute("SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias FROM flashcards").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/flashcards/today")
def get_flashcards_today():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias FROM flashcards WHERE proxima_revisao <= ?",
            (today_str(),)
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/flashcards")
def create_flashcard(body: FlashcardCreate):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, proxima_revisao) VALUES (?, ?, ?)",
            (body.pergunta, body.resposta, today_str())
        )
        conn.commit()
        new_id = cur.lastrowid
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

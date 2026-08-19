from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query

from constants import SM2_FIRST_INTERVAL, SM2_INITIAL_EF, SM2_MIN_EF, SM2_SECOND_INTERVAL, SPEED_REVIEW_LIMIT
from database import get_db_session
from logger import log
from models import (
    FlashcardCreate,
    FlashcardReview,
    FlashcardReviewResponse,
    FlashcardReviewSM2,
    FlashcardReviewSM2Response,
    OkResponse,
)
from utils import paginate, today_str, update_streak

router = APIRouter(prefix="", tags=["Flashcards"])


@router.get("/api/flashcards", summary="Listar flashcards", description="Lista todos os flashcards com paginação opcional")
def list_flashcards(page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session)):
    rows = conn.execute("SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions FROM flashcards").fetchall()
    items = [dict(r) for r in rows]
    return paginate(items, page, limit)


@router.get("/api/flashcards/today")
def get_flashcards_today(conn=Depends(get_db_session)):
    rows = conn.execute(
        "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions FROM flashcards WHERE proxima_revisao <= ?",
        (today_str(),)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/flashcards", summary="Criar flashcard", description="Cria um novo flashcard com revisão SRS")
def create_flashcard(body: FlashcardCreate, conn=Depends(get_db_session)):
    cur = conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao) VALUES (?, ?, ?)",
        (body.pergunta, body.resposta, today_str())
    )
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Flashcard created: id={new_id}")
    return {"id": new_id, "pergunta": body.pergunta, "resposta": body.resposta,
            "proxima_revisao": today_str(), "intervalo_dias": 1}


@router.post("/api/flashcards/{id}/review", response_model=FlashcardReviewResponse)
def review_flashcard(id: int, body: FlashcardReview, conn=Depends(get_db_session)):
    row = conn.execute("SELECT intervalo_dias FROM flashcards WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flashcard não encontrado")
    new_intervalo = row[0] * 2 if body.acertou else 1
    proxima = (date.today() + timedelta(days=new_intervalo)).isoformat()
    conn.execute("UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ? WHERE id = ?",
                 (new_intervalo, proxima, id))
    update_streak(conn, "flashcards_revisados")
    conn.commit()
    return {"id": id, "intervalo_dias": new_intervalo, "proxima_revisao": proxima}


@router.post("/api/flashcards/{id}/review-sm2", response_model=FlashcardReviewSM2Response)
def review_flashcard_sm2(id: int, body: FlashcardReviewSM2, conn=Depends(get_db_session)):
    """Revisão de flashcard usando algoritmo SM-2 (SuperMemo 2).
    quality: 0-5 (0=esqueceu, 3=correto com dificuldade, 5=perfeito)
    """
    row = conn.execute(
        "SELECT intervalo_dias, easiness_factor, repetitions FROM flashcards WHERE id = ?", (id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flashcard não encontrado")

    intervalo = row[0] or 1
    ef = row[1] if row[1] is not None else SM2_INITIAL_EF
    reps = row[2] if row[2] is not None else 0
    quality = body.quality

    # SM-2 Algorithm
    if quality >= 3:
        if reps == 0:
            intervalo = SM2_FIRST_INTERVAL
        elif reps == 1:
            intervalo = SM2_SECOND_INTERVAL
        else:
            intervalo = round(intervalo * ef)
        reps += 1
    else:
        reps = 0
        intervalo = 1

    # Atualizar EF
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(SM2_MIN_EF, ef)

    proxima = (date.today() + timedelta(days=intervalo)).isoformat()

    conn.execute(
        "UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ?, easiness_factor = ?, repetitions = ? WHERE id = ?",
        (intervalo, proxima, round(ef, 4), reps, id)
    )
    update_streak(conn, "flashcards_revisados")
    conn.commit()

    log.info(f"Flashcard SM-2 review: id={id} quality={quality} ef={ef:.4f} reps={reps} interval={intervalo}")
    return {
        "id": id,
        "intervalo_dias": intervalo,
        "proxima_revisao": proxima,
        "easiness_factor": round(ef, 4),
        "repetitions": reps,
        "quality": quality
    }


@router.delete("/api/flashcards/{id}", response_model=OkResponse)
def delete_flashcard(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM flashcards WHERE id = ?", (id,))
    conn.commit()
    log.info(f"Flashcard deleted: id={id}")
    return {"ok": True}


@router.get("/api/speed-review")
def speed_review(conn=Depends(get_db_session)):
    """Retorna flashcards para revisão relâmpago (modo rápido)"""
    rows = conn.execute("""
        SELECT id, pergunta, resposta FROM flashcards
        WHERE proxima_revisao <= ?
        ORDER BY intervalo_dias ASC
        LIMIT ?
    """, (today_str(), SPEED_REVIEW_LIMIT)).fetchall()
    return [{"id": r[0], "pergunta": r[1], "resposta": r[2]} for r in rows]


# ============================================================
# Exportação
# ============================================================
import csv
import io
import json

from fastapi.responses import Response


@router.get("/api/flashcards/exportar", summary="Exportar flashcards",
            description="Exporta flashcards em formato JSON, CSV ou Anki (TSV)")
def exportar_flashcards(formato: str = "json", conn=Depends(get_db_session)):
    """Formatos: json, csv, anki"""
    rows = conn.execute(
        "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions FROM flashcards ORDER BY id"
    ).fetchall()
    items = [dict(r) for r in rows]

    if formato == "csv":
        output = io.StringIO()
        if items:
            writer = csv.DictWriter(output, fieldnames=items[0].keys())
            writer.writeheader()
            writer.writerows(items)
        content = output.getvalue()
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=flashcards.csv"}
        )

    if formato == "anki":
        # Formato Anki: TSV (tab-separated) com pergunta<TAB>resposta
        # O Anki importa este formato diretamente como deck
        lines = []
        for item in items:
            # Escapar tabs e newlines
            pergunta = item["pergunta"].replace("\t", " ").replace("\n", "<br>")
            resposta = item["resposta"].replace("\t", " ").replace("\n", "<br>")
            lines.append(f"{pergunta}\t{resposta}")
        content = "\n".join(lines)
        return Response(
            content=content,
            media_type="text/tab-separated-values",
            headers={"Content-Disposition": "attachment; filename=flashcards_anki.txt"}
        )

    # JSON (default)
    content = json.dumps(items, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=flashcards.json"}
    )

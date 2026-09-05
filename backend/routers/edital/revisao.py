"""Revisão de tópicos: notas, SM2, FSRS, pendentes."""
from datetime import date, datetime, timedelta

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException
from schemas import EditalReviewSM2, NotaTopicoCreate, OkResponse

from constants import SM2_FIRST_INTERVAL, SM2_INITIAL_EF, SM2_MIN_EF, SM2_SECOND_INTERVAL
from database import get_db_session
from logger import log
from utils import today_str

router = APIRouter(prefix="", tags=["Edital"])

@router.get("/api/edital/{id}/notas")
def get_notas_topico(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM notas_topico WHERE edital_id = ? AND user_id = ? ORDER BY created_at DESC", (id, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/edital/{id}/notas")
def add_nota_topico(id: int, body: NotaTopicoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("INSERT INTO notas_topico (edital_id, conteudo, created_at, user_id) VALUES (?, ?, ?, ?)",
                       (id, body.conteudo, datetime.now().isoformat(), user_id))
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas-topico/{id}", response_model=OkResponse)
def delete_nota_topico(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM notas_topico WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


@router.post("/api/edital/{id}/agendar-revisao")
def agendar_revisao_topico(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Agenda revisão do tópico usando SM-2 com quality=4 (acertou) por default"""
    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")

    intervalo = row[0] or 1
    ef = row[1] if row[1] is not None else SM2_INITIAL_EF
    reps = row[2] if row[2] is not None else 0
    quality = 4  # default: acertou

    # SM-2 Algorithm
    if reps == 0:
        intervalo = SM2_FIRST_INTERVAL
    elif reps == 1:
        intervalo = SM2_SECOND_INTERVAL
    else:
        intervalo = round(intervalo * ef)
    reps += 1

    # Atualizar EF
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(SM2_MIN_EF, ef)

    proxima = (date.today() + timedelta(days=intervalo)).isoformat()
    conn.execute(
        "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?, easiness_factor_edital = ?, repetitions_edital = ? WHERE id = ? AND user_id = ?",
        (proxima, intervalo, round(ef, 4), reps, id, user_id)
    )
    conn.commit()
    log.info(f"Edital SM-2 revisao: id={id} quality=4 ef={ef:.4f} reps={reps} interval={intervalo}")
    return {"proxima_revisao": proxima, "intervalo": intervalo, "easiness_factor": round(ef, 4), "repetitions": reps}


@router.post("/api/edital/{id}/revisar-sm2")
def revisar_topico_sm2(id: int, body: EditalReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de tópico do edital usando SM-2 com quality variável (0-5)"""
    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")

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
        "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?, easiness_factor_edital = ?, repetitions_edital = ? WHERE id = ? AND user_id = ?",
        (proxima, intervalo, round(ef, 4), reps, id, user_id)
    )
    conn.commit()

    # Registrar tempo de revisão (~5min/tópico) + streak
    from utils import update_streak
    horas_revisao = 5 / 60  # ~5 minutos por revisão de tópico
    materia = conn.execute("SELECT materia FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    mat_nome = materia["materia"] if materia else "Revisão Edital"
    existing_sessao = conn.execute(
        "SELECT id FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'revisao_edital' AND user_id = ?",
        (today_str(), mat_nome, user_id)
    ).fetchone()
    if existing_sessao:
        conn.execute("UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                     (horas_revisao, existing_sessao["id"], user_id))
    else:
        conn.execute(
            "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, 'revisao_edital', ?, ?)",
            (mat_nome, horas_revisao, today_str(), user_id, datetime.now().isoformat())
        )
    update_streak(conn, "horas_estudadas", horas_revisao, user_id=user_id)
    conn.commit()

    log.info(f"Edital SM-2 revisar: id={id} quality={quality} ef={ef:.4f} reps={reps} interval={intervalo}")
    return {
        "id": id,
        "intervalo_dias": intervalo,
        "proxima_revisao": proxima,
        "easiness_factor": round(ef, 4),
        "repetitions": reps,
        "quality": quality
    }


@router.post("/api/edital/{id}/revisar-fsrs", summary="Revisão FSRS de tópico")
def revisar_topico_fsrs(id: int, body: EditalReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de tópico do edital usando algoritmo FSRS-5.
    quality: 0-5 (mapeado internamente para rating 1-4 do FSRS)
    """
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from fsrs import FSRSCard, review_card, sm2_to_fsrs_rating

    from constants import FSRS_DEFAULT_RETENTION

    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")

    # Try to read FSRS columns
    stability = 0.0
    difficulty = 0.0
    fsrs_state = 0
    try:
        fsrs_row = conn.execute(
            "SELECT stability_edital, difficulty_edital, fsrs_state_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
        ).fetchone()
        if fsrs_row:
            stability = fsrs_row[0] or 0.0
            difficulty = fsrs_row[1] or 0.0
            fsrs_state = fsrs_row[2] or 0
    except Exception:
        pass

    # Get desired_retention from user's metas_config
    desired_retention = FSRS_DEFAULT_RETENTION
    try:
        meta_row = conn.execute(
            "SELECT desired_retention FROM metas_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if meta_row and meta_row[0]:
            desired_retention = meta_row[0]
    except Exception:
        pass

    # Build FSRS card state
    reps = row[2] if row[2] is not None else 0
    card = FSRSCard(
        stability=stability,
        difficulty=difficulty,
        state=fsrs_state,
        reps=reps
    )

    # Map SM-2 quality (0-5) to FSRS rating (1-4)
    rating = sm2_to_fsrs_rating(body.quality)

    # Call FSRS algorithm
    output = review_card(card, rating, desired_retention=desired_retention)

    proxima = (date.today() + timedelta(days=output.interval)).isoformat()
    new_reps = reps + 1

    # Update edital with FSRS results
    try:
        conn.execute(
            """UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?,
               stability_edital = ?, difficulty_edital = ?, fsrs_state_edital = ?, repetitions_edital = ?
               WHERE id = ? AND user_id = ?""",
            (proxima, output.interval, round(output.stability, 6),
             round(output.difficulty, 4), output.state, new_reps, id, user_id)
        )
    except Exception:
        # Fallback if FSRS columns don't exist
        conn.execute(
            "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ? WHERE id = ? AND user_id = ?",
            (proxima, output.interval, id, user_id)
        )

    conn.commit()

    # Registrar tempo de revisão (~5min/tópico) + streak
    from utils import update_streak
    horas_revisao = 5 / 60
    materia_row = conn.execute("SELECT materia FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    mat_nome = materia_row["materia"] if materia_row else "Revisão Edital"
    existing_sessao = conn.execute(
        "SELECT id FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'revisao_edital' AND user_id = ?",
        (today_str(), mat_nome, user_id)
    ).fetchone()
    if existing_sessao:
        conn.execute("UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                     (horas_revisao, existing_sessao["id"], user_id))
    else:
        conn.execute(
            "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, 'revisao_edital', ?, ?)",
            (mat_nome, horas_revisao, today_str(), user_id, datetime.now().isoformat())
        )
    update_streak(conn, "horas_estudadas", horas_revisao, user_id=user_id)
    conn.commit()

    log.info(f"Edital FSRS revisar: id={id} rating={rating} S={output.stability:.4f} D={output.difficulty:.4f} I={output.interval}")
    return {
        "id": id,
        "intervalo_dias": output.interval,
        "proxima_revisao": proxima,
        "stability": round(output.stability, 6),
        "difficulty": round(output.difficulty, 4),
        "fsrs_state": output.state,
        "repetitions": new_reps,
        "rating": rating,
        "retrievability": round(output.retrievability, 4) if output.retrievability else None
    }


@router.get("/api/edital/revisoes-pendentes")
def revisoes_pendentes(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista tópicos com revisão pendente (SRS)"""
    try:
        rows = conn.execute("""
            SELECT id, edital_nome, cargo, materia, topico, proxima_revisao
            FROM edital
            WHERE proxima_revisao != '' AND proxima_revisao <= ? AND user_id = ?
            ORDER BY proxima_revisao
        """, (today_str(), user_id)).fetchall()
    except Exception as e:
        log.warning(f"Could not query pending reviews: {e}")
        rows = []
    return [dict(r) for r in rows]



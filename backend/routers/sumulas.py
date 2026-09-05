from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from constants import SM2_FIRST_INTERVAL, SM2_INITIAL_EF, SM2_MIN_EF, SM2_SECOND_INTERVAL
from database import get_db_session
from logger import log
from utils import today_str, update_streak

router = APIRouter(prefix="", tags=["Súmulas"])


# ============================================================
# MODELS
# ============================================================

class SumulaCreate(BaseModel):
    tribunal: str  # STF, STJ, TST, TSE
    numero: int
    enunciado: str
    tema: str = ""
    observacao: str = ""
    vinculante: bool = False


class SumulaUpdate(BaseModel):
    tribunal: str | None = None
    numero: int | None = None
    enunciado: str | None = None
    tema: str | None = None
    observacao: str | None = None
    vinculante: bool | None = None


class SumulaReviewSM2(BaseModel):
    quality: int = Field(ge=0, le=5, description="0=esqueceu, 3=difícil, 5=fácil")


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/api/sumulas", summary="Listar súmulas")
def list_sumulas(tribunal: str = "", tema: str = "", page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT * FROM sumulas WHERE user_id = ?"
    params = [user_id]
    if tribunal:
        query += " AND tribunal = ?"
        params.append(tribunal)
    if tema:
        query += " AND tema = ?"
        params.append(tema)
    query += " ORDER BY tribunal, numero"
    rows = conn.execute(query, params).fetchall()
    items = [dict(r) for r in rows]
    if page is not None:
        start = (page - 1) * limit
        return items[start:start + limit]
    return items


@router.get("/api/sumulas/today", summary="Súmulas do dia (revisão SRS)")
def get_sumulas_today(tribunal: str = "", tema: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna súmulas pendentes para hoje com ordenação inteligente baseada em 6 técnicas
    de estudo com evidência científica (spaced practice, interleaving, desirable difficulty,
    retrieval practice, successive relearning, pre-testing effect).
    """
    from study_ordering import order_items_intelligently

    query = "SELECT * FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?"
    params = [today_str(), user_id]
    if tribunal:
        query += " AND tribunal = ?"
        params.append(tribunal)
    if tema:
        query += " AND tema = ?"
        params.append(tema)
    rows = conn.execute(query, params).fetchall()
    items = [dict(r) for r in rows]

    if not items:
        return []

    # Importância: súmulas vinculantes têm peso 2x
    def importance(item):
        return 2.0 if item.get("vinculante") else 1.0

    result = order_items_intelligently(
        items,
        materia_key="tema",  # Interleaving por tema (fallback: tribunal)
        importance_fn=importance,
    )

    # Limpar campos internos
    for s in result:
        s.pop("_expanding_retrieval", None)

    return result


@router.get("/api/sumulas/stats", summary="Estatísticas de súmulas")
def get_sumulas_stats(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    total = conn.execute("SELECT COUNT(*) FROM sumulas WHERE user_id = ?", (user_id,)).fetchone()[0]
    pendentes = conn.execute("SELECT COUNT(*) FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)).fetchone()[0]
    por_tribunal = conn.execute("SELECT tribunal, COUNT(*) as total FROM sumulas WHERE user_id = ? GROUP BY tribunal ORDER BY total DESC", (user_id,)).fetchall()
    por_tema = conn.execute("SELECT tema, COUNT(*) as total FROM sumulas WHERE tema != '' AND user_id = ? GROUP BY tema ORDER BY total DESC", (user_id,)).fetchall()
    dominadas = conn.execute("SELECT COUNT(*) FROM sumulas WHERE repetitions >= 5 AND easiness_factor > 2.5 AND user_id = ?", (user_id,)).fetchone()[0]
    return {
        "total": total,
        "pendentes_hoje": pendentes,
        "dominadas": dominadas,
        "por_tribunal": [dict(r) for r in por_tribunal],
        "por_tema": [dict(r) for r in por_tema],
    }


@router.get("/api/sumulas/tribunais", summary="Listar tribunais disponíveis")
def list_tribunais(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT tribunal, COUNT(*) as total FROM sumulas WHERE user_id = ? GROUP BY tribunal ORDER BY total DESC", (user_id,)).fetchall()
    return [{"tribunal": r[0], "total": r[1]} for r in rows]


@router.get("/api/sumulas/temas", summary="Listar temas disponíveis")
def list_temas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT tema, COUNT(*) as total FROM sumulas WHERE tema != '' AND user_id = ? GROUP BY tema ORDER BY total DESC", (user_id,)).fetchall()
    return [{"tema": r[0], "total": r[1]} for r in rows]


@router.post("/api/sumulas", summary="Criar súmula")
def create_sumula(body: SumulaCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO sumulas (tribunal, numero, enunciado, tema, observacao, vinculante, proxima_revisao, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (body.tribunal, body.numero, body.enunciado, body.tema, body.observacao, int(body.vinculante), today_str(), user_id)
    )
    conn.commit()
    log.info(f"Súmula criada: {body.tribunal} {body.numero}")
    return {"id": cur.lastrowid, "ok": True}


@router.put("/api/sumulas/{id}", summary="Editar súmula")
def update_sumula(id: int, body: SumulaUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT id FROM sumulas WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Súmula não encontrada")
    updates = []
    params = []
    if body.tribunal is not None:
        updates.append("tribunal = ?")
        params.append(body.tribunal)
    if body.numero is not None:
        updates.append("numero = ?")
        params.append(body.numero)
    if body.enunciado is not None:
        updates.append("enunciado = ?")
        params.append(body.enunciado)
    if body.tema is not None:
        updates.append("tema = ?")
        params.append(body.tema)
    if body.observacao is not None:
        updates.append("observacao = ?")
        params.append(body.observacao)
    if body.vinculante is not None:
        updates.append("vinculante = ?")
        params.append(int(body.vinculante))
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    params.append(id)
    params.append(user_id)
    conn.execute(f"UPDATE sumulas SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
    conn.commit()
    return {"ok": True}


@router.delete("/api/sumulas/{id}", summary="Excluir súmula")
def delete_sumula(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM sumulas WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Súmula deletada: id={id}")
    return {"ok": True}


@router.post("/api/sumulas/{id}/review-sm2", summary="Revisar súmula (SM-2)")
def review_sumula_sm2(id: int, body: SumulaReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de súmula usando algoritmo SM-2.
    quality: 0-5 (0=esqueceu completamente, 5=lembrou perfeitamente)
    """
    row = conn.execute(
        "SELECT intervalo_dias, easiness_factor, repetitions FROM sumulas WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Súmula não encontrada")

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
        "UPDATE sumulas SET intervalo_dias = ?, proxima_revisao = ?, easiness_factor = ?, repetitions = ? WHERE id = ? AND user_id = ?",
        (intervalo, proxima, round(ef, 4), reps, id, user_id)
    )
    # Atualizar streak: conta como revisão SRS E como súmula revisada
    update_streak(conn, "flashcards_revisados", user_id=user_id)
    conn.execute("""
        INSERT INTO streaks (data, sumulas_revisadas, user_id) VALUES (?, 1, ?)
        ON CONFLICT(user_id, data) DO UPDATE SET sumulas_revisadas = COALESCE(sumulas_revisadas, 0) + 1
    """, (today_str(), user_id))

    # Registrar tempo de revisão (~30s/súmula)
    horas_rev = 0.5 / 60  # 30 segundos
    existing_sessao = conn.execute(
        "SELECT id FROM sessoes_estudo WHERE data = ? AND tipo = 'sumulas' AND user_id = ?",
        (today_str(), user_id)
    ).fetchone()
    if existing_sessao:
        conn.execute("UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                     (horas_rev, existing_sessao["id"], user_id))
    else:
        from datetime import datetime
        conn.execute(
            "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, 'sumulas', ?, ?)",
            ("Súmulas (Revisão)", horas_rev, today_str(), user_id, datetime.now().isoformat())
        )
    conn.commit()

    log.info(f"Súmula SM-2: id={id} quality={quality} ef={ef:.4f} reps={reps} interval={intervalo}")
    return {
        "id": id,
        "intervalo_dias": intervalo,
        "proxima_revisao": proxima,
        "easiness_factor": round(ef, 4),
        "repetitions": reps,
        "quality": quality
    }


@router.post("/api/sumulas/{id}/review-fsrs", summary="Revisar súmula (FSRS)")
def review_sumula_fsrs(id: int, body: SumulaReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de súmula usando algoritmo FSRS-5.
    quality: 0-5 (mapeado internamente para rating 1-4 do FSRS)
    """
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from fsrs import FSRSCard, review_card, sm2_to_fsrs_rating

    from constants import FSRS_DEFAULT_RETENTION

    row = conn.execute(
        "SELECT intervalo_dias, easiness_factor, repetitions FROM sumulas WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Súmula não encontrada")

    # Try to read FSRS columns
    stability = 0.0
    difficulty = 0.0
    fsrs_state = 0
    try:
        fsrs_row = conn.execute(
            "SELECT stability, difficulty_sumulas, fsrs_state FROM sumulas WHERE id = ? AND user_id = ?", (id, user_id)
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

    # Update sumula with FSRS results
    try:
        conn.execute(
            """UPDATE sumulas SET intervalo_dias = ?, proxima_revisao = ?,
               stability = ?, difficulty_sumulas = ?, fsrs_state = ?, repetitions = ?
               WHERE id = ? AND user_id = ?""",
            (output.interval, proxima, round(output.stability, 6),
             round(output.difficulty, 4), output.state, new_reps, id, user_id)
        )
    except Exception:
        # Fallback if FSRS columns don't exist
        conn.execute(
            "UPDATE sumulas SET intervalo_dias = ?, proxima_revisao = ? WHERE id = ? AND user_id = ?",
            (output.interval, proxima, id, user_id)
        )

    # Update streak
    update_streak(conn, "flashcards_revisados", user_id=user_id)
    conn.execute("""
        INSERT INTO streaks (data, sumulas_revisadas, user_id) VALUES (?, 1, ?)
        ON CONFLICT(user_id, data) DO UPDATE SET sumulas_revisadas = COALESCE(sumulas_revisadas, 0) + 1
    """, (today_str(), user_id))
    conn.commit()

    log.info(f"Súmula FSRS: id={id} rating={rating} S={output.stability:.4f} D={output.difficulty:.4f} I={output.interval}")
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


@router.post("/api/sumulas/importar", summary="Importar súmulas em lote")
def importar_sumulas(body: list = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Importa lista de súmulas. Body: [{tribunal, numero, enunciado, tema?, observacao?, vinculante?}]"""
    count = 0
    duplicadas = 0
    for item in body:
        tribunal = item.get("tribunal", "")
        numero = item.get("numero", 0)
        enunciado = item.get("enunciado", "")
        if not tribunal or not numero or not enunciado:
            continue
        # Verificar duplicata
        existing = conn.execute(
            "SELECT id FROM sumulas WHERE tribunal = ? AND numero = ? AND user_id = ?", (tribunal, numero, user_id)
        ).fetchone()
        if existing:
            duplicadas += 1
            continue
        tema = item.get("tema", "")
        observacao = item.get("observacao", "")
        vinculante = int(item.get("vinculante", False))
        conn.execute(
            "INSERT INTO sumulas (tribunal, numero, enunciado, tema, observacao, vinculante, proxima_revisao, user_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (tribunal, numero, enunciado, tema, observacao, vinculante, today_str(), user_id)
        )
        count += 1
    conn.commit()
    log.info(f"Súmulas importadas: {count} novas, {duplicadas} duplicadas ignoradas")
    return {"ok": True, "importadas": count, "duplicadas": duplicadas}


@router.get("/api/sumulas/aleatorio", summary="Súmulas aleatórias para estudo")
def get_sumulas_aleatorio(tribunal: str = "", tema: str = "", quantidade: int = 10, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT * FROM sumulas WHERE user_id = ?"
    params = [user_id]
    if tribunal:
        query += " AND tribunal = ?"
        params.append(tribunal)
    if tema:
        query += " AND tema = ?"
        params.append(tema)
    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(quantidade)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]

from datetime import date, timedelta

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
def list_sumulas(tribunal: str = "", tema: str = "", page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session)):
    query = "SELECT * FROM sumulas WHERE 1=1"
    params = []
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
def get_sumulas_today(tribunal: str = "", tema: str = "", conn=Depends(get_db_session)):
    query = "SELECT * FROM sumulas WHERE proxima_revisao <= ?"
    params = [today_str()]
    if tribunal:
        query += " AND tribunal = ?"
        params.append(tribunal)
    if tema:
        query += " AND tema = ?"
        params.append(tema)
    query += " ORDER BY intervalo_dias ASC"
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/sumulas/stats", summary="Estatísticas de súmulas")
def get_sumulas_stats(conn=Depends(get_db_session)):
    total = conn.execute("SELECT COUNT(*) FROM sumulas").fetchone()[0]
    pendentes = conn.execute("SELECT COUNT(*) FROM sumulas WHERE proxima_revisao <= ?", (today_str(),)).fetchone()[0]
    por_tribunal = conn.execute("SELECT tribunal, COUNT(*) as total FROM sumulas GROUP BY tribunal ORDER BY total DESC").fetchall()
    por_tema = conn.execute("SELECT tema, COUNT(*) as total FROM sumulas WHERE tema != '' GROUP BY tema ORDER BY total DESC").fetchall()
    dominadas = conn.execute("SELECT COUNT(*) FROM sumulas WHERE repetitions >= 5 AND easiness_factor > 2.5").fetchone()[0]
    return {
        "total": total,
        "pendentes_hoje": pendentes,
        "dominadas": dominadas,
        "por_tribunal": [dict(r) for r in por_tribunal],
        "por_tema": [dict(r) for r in por_tema],
    }


@router.get("/api/sumulas/tribunais", summary="Listar tribunais disponíveis")
def list_tribunais(conn=Depends(get_db_session)):
    rows = conn.execute("SELECT tribunal, COUNT(*) as total FROM sumulas GROUP BY tribunal ORDER BY total DESC").fetchall()
    return [{"tribunal": r[0], "total": r[1]} for r in rows]


@router.get("/api/sumulas/temas", summary="Listar temas disponíveis")
def list_temas(conn=Depends(get_db_session)):
    rows = conn.execute("SELECT tema, COUNT(*) as total FROM sumulas WHERE tema != '' GROUP BY tema ORDER BY total DESC").fetchall()
    return [{"tema": r[0], "total": r[1]} for r in rows]


@router.post("/api/sumulas", summary="Criar súmula")
def create_sumula(body: SumulaCreate, conn=Depends(get_db_session)):
    cur = conn.execute(
        "INSERT INTO sumulas (tribunal, numero, enunciado, tema, observacao, vinculante, proxima_revisao) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.tribunal, body.numero, body.enunciado, body.tema, body.observacao, int(body.vinculante), today_str())
    )
    conn.commit()
    log.info(f"Súmula criada: {body.tribunal} {body.numero}")
    return {"id": cur.lastrowid, "ok": True}


@router.put("/api/sumulas/{id}", summary="Editar súmula")
def update_sumula(id: int, body: SumulaUpdate, conn=Depends(get_db_session)):
    row = conn.execute("SELECT id FROM sumulas WHERE id = ?", (id,)).fetchone()
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
    conn.execute(f"UPDATE sumulas SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    return {"ok": True}


@router.delete("/api/sumulas/{id}", summary="Excluir súmula")
def delete_sumula(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM sumulas WHERE id = ?", (id,))
    conn.commit()
    log.info(f"Súmula deletada: id={id}")
    return {"ok": True}


@router.post("/api/sumulas/{id}/review-sm2", summary="Revisar súmula (SM-2)")
def review_sumula_sm2(id: int, body: SumulaReviewSM2, conn=Depends(get_db_session)):
    """Revisão de súmula usando algoritmo SM-2.
    quality: 0-5 (0=esqueceu completamente, 5=lembrou perfeitamente)
    """
    row = conn.execute(
        "SELECT intervalo_dias, easiness_factor, repetitions FROM sumulas WHERE id = ?", (id,)
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
        "UPDATE sumulas SET intervalo_dias = ?, proxima_revisao = ?, easiness_factor = ?, repetitions = ? WHERE id = ?",
        (intervalo, proxima, round(ef, 4), reps, id)
    )
    # Atualizar streak: conta como revisão SRS E como súmula revisada
    update_streak(conn, "flashcards_revisados")
    conn.execute("""
        INSERT INTO streaks (data, sumulas_revisadas) VALUES (?, 1)
        ON CONFLICT(data) DO UPDATE SET sumulas_revisadas = COALESCE(sumulas_revisadas, 0) + 1
    """, (today_str(),))
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


@router.post("/api/sumulas/importar", summary="Importar súmulas em lote")
def importar_sumulas(body: list = Body(...), conn=Depends(get_db_session)):
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
            "SELECT id FROM sumulas WHERE tribunal = ? AND numero = ?", (tribunal, numero)
        ).fetchone()
        if existing:
            duplicadas += 1
            continue
        tema = item.get("tema", "")
        observacao = item.get("observacao", "")
        vinculante = int(item.get("vinculante", False))
        conn.execute(
            "INSERT INTO sumulas (tribunal, numero, enunciado, tema, observacao, vinculante, proxima_revisao) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tribunal, numero, enunciado, tema, observacao, vinculante, today_str())
        )
        count += 1
    conn.commit()
    log.info(f"Súmulas importadas: {count} novas, {duplicadas} duplicadas ignoradas")
    return {"ok": True, "importadas": count, "duplicadas": duplicadas}


@router.get("/api/sumulas/aleatorio", summary="Súmulas aleatórias para estudo")
def get_sumulas_aleatorio(tribunal: str = "", tema: str = "", quantidade: int = 10, conn=Depends(get_db_session)):
    query = "SELECT * FROM sumulas WHERE 1=1"
    params = []
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

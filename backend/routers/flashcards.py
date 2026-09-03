from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from constants import SM2_FIRST_INTERVAL, SM2_INITIAL_EF, SM2_MIN_EF, SM2_SECOND_INTERVAL, SPEED_REVIEW_LIMIT
from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import (
    FlashcardCreate,
    FlashcardReview,
    FlashcardReviewResponse,
    FlashcardReviewSM2,
    FlashcardReviewSM2Response,
    FlashcardUpdate,
    OkResponse,
)
from sanitize import sanitize_input
from utils import sql_paginate, today_str, update_streak

router = APIRouter(prefix="", tags=["Flashcards"])


@router.get("/api/flashcards", summary="Listar flashcards", description="Lista todos os flashcards com paginação opcional e filtro por matéria")
def list_flashcards(materia: str = "", page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if materia:
        query = "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, stability, fsrs_state FROM flashcards WHERE materia = ? AND user_id = ?"
        params = (materia, user_id)
    else:
        query = "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, stability, fsrs_state FROM flashcards WHERE user_id = ?"
        params = (user_id,)
    return sql_paginate(conn, query, params, page, limit)


@router.get("/api/flashcards/materias", summary="Listar matérias dos flashcards")
def list_flashcards_materias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT materia, COUNT(*) as total FROM flashcards WHERE user_id = ? GROUP BY materia ORDER BY total DESC", (user_id,)).fetchall()
    return [{"materia": r[0] or "Sem matéria", "total": r[1]} for r in rows]


@router.get("/api/flashcards/today")
def get_flashcards_today(materia: str = "", max_novos: int = Query(20, description="Máximo de flashcards novos por dia (padrão 20, como Anki)"), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna flashcards pendentes com ordenação inteligente baseada em FSRS state.

    Prioridade de revisão (baseado em evidência científica):
    1. Relearning (fsrs_state=3) — cards que foram esquecidos recentemente
    2. Learning (fsrs_state=1) — cards em fase inicial de aprendizado
    3. Review (fsrs_state=2) — cards maduros que venceram o intervalo
    4. New (fsrs_state=0) — cards nunca vistos (limitados a max_novos/dia)

    Dentro de cada grupo, aplica interleaving por matéria para maximizar retenção.
    Limita novos cards (repetitions=0) a max_novos por dia (padrão 20).
    Reviews (cards já revisados antes) não têm limite.
    """
    from study_ordering import order_items_intelligently

    if materia:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state FROM flashcards WHERE proxima_revisao <= ? AND materia = ? AND user_id = ?",
            (today_str(), materia, user_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia, fsrs_state FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
            (today_str(), user_id)
        ).fetchall()
    items = [dict(r) for r in rows]

    if not items:
        return []

    # Separar por estado FSRS (prioridade de revisão)
    relearning = [c for c in items if (c.get("fsrs_state") or 0) == 3]  # Esquecidos
    learning = [c for c in items if (c.get("fsrs_state") or 0) == 1]    # Aprendendo
    review = [c for c in items if (c.get("fsrs_state") or 0) == 2]      # Maduros vencidos
    new_cards = [c for c in items if (c.get("fsrs_state") or 0) == 0]   # Novos

    # Limitar novos cards por dia (como Anki: padrão 20)
    novos_limitados = new_cards[:max_novos]

    # Combinar na ordem de prioridade FSRS
    combined = relearning + learning + review + novos_limitados

    result = order_items_intelligently(
        combined,
        materia_key="materia",
    )

    # Limpar campos internos
    for card in result:
        card.pop("_expanding_retrieval", None)
        card.pop("fsrs_state", None)

    return result


@router.get("/api/flashcards/today-count", summary="Contagem de flashcards de hoje (pendentes e revisados)")
def get_flashcards_today_count(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Contagem flashcard-específica para a barra de progresso da revisão.

    - pendentes: flashcards com proxima_revisao <= hoje (mesmo critério do badge).
    - revisados_hoje: flashcards efetivamente revisados HOJE (via ultima_revisao),
      SEM contaminação de súmulas/outros modos (ao contrário de
      streaks.flashcards_revisados). Usado para exibir "X/Y" corretamente
      inclusive ao voltar à aba.
    """
    hoje = today_str()
    pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id),
    ).fetchone()[0]
    try:
        revisados_hoje = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE ultima_revisao = ? AND user_id = ?",
            (hoje, user_id),
        ).fetchone()[0]
    except Exception:
        revisados_hoje = 0  # coluna ainda não existe (pré-migração)
    return {"pendentes": pendentes, "revisados_hoje": revisados_hoje}


@router.get("/api/flashcards/aleatorio", summary="Flashcards aleatórios para estudo")
def get_flashcards_aleatorio(materia: str = "", quantidade: int = 10, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna flashcards aleatórios para sessão de estudo (por disciplina ou todas)"""
    if materia:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, materia FROM flashcards WHERE materia = ? AND user_id = ? ORDER BY RANDOM() LIMIT ?",
            (materia, user_id, quantidade)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, materia FROM flashcards WHERE user_id = ? ORDER BY RANDOM() LIMIT ?",
            (user_id, quantidade)
        ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/flashcards", summary="Criar flashcard", description="Cria um novo flashcard com revisão SRS")
def create_flashcard(body: FlashcardCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from plans import enforce_plan_limit
    enforce_plan_limit(conn, user_id, "flashcards")

    pergunta = sanitize_input(body.pergunta, max_length=2000)
    resposta = sanitize_input(body.resposta, max_length=5000)
    materia = sanitize_input(getattr(body, 'materia', ''))
    cur = conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id) VALUES (?, ?, ?, ?, ?)",
        (pergunta, resposta, today_str(), materia, user_id)
    )
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Flashcard created: id={new_id}")
    return {"id": new_id, "pergunta": pergunta, "resposta": resposta,
            "proxima_revisao": today_str(), "intervalo_dias": 1}


@router.post("/api/flashcards/{id}/review", response_model=FlashcardReviewResponse)
def review_flashcard(id: int, body: FlashcardReview, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT intervalo_dias FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flashcard não encontrado")
    new_intervalo = row[0] * 2 if body.acertou else 1
    proxima = (date.today() + timedelta(days=new_intervalo)).isoformat()
    conn.execute("UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ?, ultima_revisao = ? WHERE id = ? AND user_id = ?",
                 (new_intervalo, proxima, today_str(), id, user_id))
    update_streak(conn, "flashcards_revisados", user_id=user_id)
    conn.commit()

    # A3: Suggest elaboration when user got it wrong
    result = {"id": id, "intervalo_dias": new_intervalo, "proxima_revisao": proxima, "elaboration_suggested": not body.acertou}
    if not body.acertou:
        flash_row = conn.execute(
            "SELECT pergunta, resposta, materia FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)
        ).fetchone()
        if flash_row:
            result["elaboration_prompts"] = _build_elaboration_prompts(
                flash_row["pergunta"], flash_row["resposta"], flash_row["materia"] or ""
            )
    return result


@router.post("/api/flashcards/{id}/review-sm2", response_model=FlashcardReviewSM2Response)
def review_flashcard_sm2(id: int, body: FlashcardReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de flashcard usando algoritmo SM-2 (SuperMemo 2).
    quality: 0-5 (0=esqueceu, 3=correto com dificuldade, 5=perfeito)
    """
    row = conn.execute(
        "SELECT intervalo_dias, easiness_factor, repetitions FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)
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
        "UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ?, easiness_factor = ?, repetitions = ?, ultima_revisao = ? WHERE id = ? AND user_id = ?",
        (intervalo, proxima, round(ef, 4), reps, today_str(), id, user_id)
    )
    update_streak(conn, "flashcards_revisados", user_id=user_id)
    conn.commit()

    log.info(f"Flashcard SM-2 review: id={id} quality={quality} ef={ef:.4f} reps={reps} interval={intervalo}")

    # A3: Suggest elaboration when rating is low (quality < 3)
    elaboration_suggested = quality < 3
    result = {
        "id": id,
        "intervalo_dias": intervalo,
        "proxima_revisao": proxima,
        "easiness_factor": round(ef, 4),
        "repetitions": reps,
        "quality": quality,
        "elaboration_suggested": elaboration_suggested,
    }
    if elaboration_suggested:
        # Generate inline elaboration prompts
        flash_row = conn.execute(
            "SELECT pergunta, resposta, materia FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)
        ).fetchone()
        if flash_row:
            result["elaboration_prompts"] = _build_elaboration_prompts(
                flash_row["pergunta"], flash_row["resposta"], flash_row["materia"] or ""
            )
    return result


@router.post("/api/flashcards/{id}/review-fsrs", summary="Revisão FSRS")
def review_flashcard_fsrs(id: int, body: FlashcardReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de flashcard usando algoritmo FSRS-5.
    quality: 0-5 (mapeado internamente para rating 1-4 do FSRS)
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from fsrs import FSRSCard, review_card, sm2_to_fsrs_rating
    from constants import FSRS_DEFAULT_RETENTION

    row = conn.execute(
        "SELECT intervalo_dias, easiness_factor, repetitions FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flashcard não encontrado")

    # Try to read FSRS columns (may not exist yet)
    stability = 0.0
    difficulty = 0.0
    fsrs_state = 0
    try:
        fsrs_row = conn.execute(
            "SELECT stability, difficulty, fsrs_state FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)
        ).fetchone()
        if fsrs_row:
            stability = fsrs_row[0] or 0.0
            difficulty = fsrs_row[1] or 0.0
            fsrs_state = fsrs_row[2] or 0
    except Exception:
        pass  # FSRS columns don't exist yet, use defaults

    # Get desired_retention from user's metas_config
    desired_retention = FSRS_DEFAULT_RETENTION
    try:
        meta_row = conn.execute(
            "SELECT desired_retention FROM metas_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if meta_row and meta_row[0]:
            desired_retention = meta_row[0]
    except Exception:
        pass  # Column doesn't exist yet

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

    # === LAG EFFECT (Exam-Aware Spacing) — centralizado em study_techniques ===
    # Cepeda et al. (2006): comprime o intervalo conforme a proximidade da prova.
    from study_techniques import apply_lag_effect
    adjusted_interval = apply_lag_effect(conn, user_id, output.interval)

    proxima = (date.today() + timedelta(days=adjusted_interval)).isoformat()
    new_reps = reps + 1

    # Update flashcard with FSRS results
    try:
        conn.execute(
            """UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ?,
               stability = ?, difficulty = ?, fsrs_state = ?, repetitions = ?, ultima_revisao = ?
               WHERE id = ? AND user_id = ?""",
            (adjusted_interval, proxima, round(output.stability, 6),
             round(output.difficulty, 4), output.state, new_reps, today_str(), id, user_id)
        )
    except Exception:
        # Fallback if FSRS columns don't exist - just update interval and next review
        conn.execute(
            "UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ? WHERE id = ? AND user_id = ?",
            (adjusted_interval, proxima, id, user_id)
        )

    update_streak(conn, "flashcards_revisados", user_id=user_id)
    conn.commit()

    log.info(f"Flashcard FSRS review: id={id} rating={rating} S={output.stability:.4f} D={output.difficulty:.4f} I={output.interval} adj_I={adjusted_interval}")

    # A3: Suggest elaboration when rating is low (FSRS rating 1 = Again, 2 = Hard)
    elaboration_suggested = rating <= 2
    result = {
        "id": id,
        "intervalo_dias": adjusted_interval,
        "proxima_revisao": proxima,
        "stability": round(output.stability, 6),
        "difficulty": round(output.difficulty, 4),
        "fsrs_state": output.state,
        "repetitions": new_reps,
        "rating": rating,
        "retrievability": round(output.retrievability, 4) if output.retrievability else None,
        "elaboration_suggested": elaboration_suggested,
    }
    if elaboration_suggested:
        flash_row = conn.execute(
            "SELECT pergunta, resposta, materia FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)
        ).fetchone()
        if flash_row:
            result["elaboration_prompts"] = _build_elaboration_prompts(
                flash_row["pergunta"], flash_row["resposta"], flash_row["materia"] or ""
            )
    return result


@router.post("/api/flashcards/migrate-to-fsrs", summary="Migrar cards SM-2 para FSRS",
             description="Migra todos os flashcards que ainda usam SM-2 para estado FSRS equivalente.")
def migrate_flashcards_to_fsrs(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Migra cards existentes de SM-2 para FSRS-5.

    - Cards com reps > 0: converte EF/interval/reps para stability/difficulty/state FSRS
    - Cards novos (reps=0): reseta para estado FSRS New (serão agendados no primeiro review)
    - Recalcula proxima_revisao baseado na stability FSRS
    """
    from fsrs import migrate_sm2_to_fsrs, _next_interval, STATE_NEW, STATE_REVIEW
    from constants import FSRS_DEFAULT_RETENTION

    # Obter desired_retention do user
    desired_retention = FSRS_DEFAULT_RETENTION
    try:
        meta_row = conn.execute(
            "SELECT desired_retention FROM metas_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if meta_row and meta_row[0]:
            desired_retention = meta_row[0]
    except Exception:
        pass

    # Buscar cards que ainda não foram migrados (stability = 0 indica não-migrado)
    rows = conn.execute("""
        SELECT id, easiness_factor, repetitions, intervalo_dias, proxima_revisao
        FROM flashcards WHERE user_id = ? AND (stability IS NULL OR stability = 0)
    """, (user_id,)).fetchall()

    migrated = 0
    for r in rows:
        ef = r["easiness_factor"] if r["easiness_factor"] else 2.5
        reps = r["repetitions"] if r["repetitions"] else 0
        interval = r["intervalo_dias"] if r["intervalo_dias"] else 1

        if reps == 0:
            # Card novo: manter como STATE_NEW, será agendado no primeiro review
            conn.execute("""
                UPDATE flashcards SET stability = 0, difficulty = 0, fsrs_state = 0
                WHERE id = ? AND user_id = ?
            """, (r["id"], user_id))
        else:
            # Card já revisado: converter SM-2 → FSRS
            fsrs_card = migrate_sm2_to_fsrs(ef, reps, interval)
            # Recalcular próxima revisão baseado na nova stability
            new_interval = _next_interval(fsrs_card.stability, desired_retention)
            # Manter a proxima_revisao original se ainda não venceu, senão recalcular
            proxima = r["proxima_revisao"]
            if not proxima or proxima <= date.today().isoformat():
                proxima = (date.today() + timedelta(days=1)).isoformat()

            conn.execute("""
                UPDATE flashcards SET stability = ?, difficulty = ?, fsrs_state = ?,
                       intervalo_dias = ?, proxima_revisao = ?
                WHERE id = ? AND user_id = ?
            """, (round(fsrs_card.stability, 6), round(fsrs_card.difficulty, 4),
                  fsrs_card.state, new_interval, proxima, r["id"], user_id))
        migrated += 1

    conn.commit()
    log.info(f"FSRS migration: {migrated} cards migrated for user {user_id}")
    return {"ok": True, "migrated": migrated, "total": len(rows)}


@router.put("/api/flashcards/{id}", summary="Editar flashcard", description="Atualiza pergunta, resposta e/ou matéria de um flashcard")
def update_flashcard(id: int, body: FlashcardUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT id FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flashcard não encontrado")
    updates = []
    params = []
    if body.pergunta is not None:
        updates.append("pergunta = ?")
        params.append(sanitize_input(body.pergunta, max_length=2000))
    if body.resposta is not None:
        updates.append("resposta = ?")
        params.append(sanitize_input(body.resposta, max_length=5000))
    if body.materia is not None:
        updates.append("materia = ?")
        params.append(sanitize_input(body.materia))
    if not updates:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    params.append(id)
    params.append(user_id)
    conn.execute(f"UPDATE flashcards SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
    conn.commit()
    updated = conn.execute(
        "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia FROM flashcards WHERE id = ? AND user_id = ?",
        (id, user_id)
    ).fetchone()
    log.info(f"Flashcard updated: id={id}")
    return dict(updated)


@router.get("/api/edital/materias-disponiveis", summary="Listar disciplinas do edital",
            description="Retorna todas as disciplinas distintas cadastradas no edital para vincular a flashcards")
def list_materias_disponiveis(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT DISTINCT materia FROM edital WHERE user_id = ? ORDER BY materia", (user_id,)).fetchall()
    return [r[0] for r in rows if r[0]]


@router.delete("/api/flashcards/{id}", response_model=OkResponse)
def delete_flashcard(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM flashcards WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Flashcard deleted: id={id}")
    return {"ok": True}


@router.get("/api/speed-review")
def speed_review(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna flashcards para revisão relâmpago (modo rápido)"""
    rows = conn.execute("""
        SELECT id, pergunta, resposta FROM flashcards
        WHERE proxima_revisao <= ? AND user_id = ?
        ORDER BY intervalo_dias ASC
        LIMIT ?
    """, (today_str(), user_id, SPEED_REVIEW_LIMIT)).fetchall()
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
def exportar_flashcards(formato: str = "json", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Formatos: json, csv, anki"""
    rows = conn.execute(
        "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions FROM flashcards WHERE user_id = ? ORDER BY id",
        (user_id,)
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


@router.post("/api/flashcards/importar", summary="Importar flashcards",
             description="Importa flashcards de JSON, CSV ou formato Anki (TSV)")
def importar_flashcards(file: UploadFile = File(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Aceita JSON, CSV (colunas: pergunta, resposta, [materia]) ou Anki TSV (pergunta<TAB>resposta)"""
    content = file.file.read()
    text = content.decode("utf-8-sig")  # utf-8-sig remove BOM se presente (Excel)
    items = []

    filename = (file.filename or "").lower()

    def _pick(row: dict, *aliases: str) -> str:
        """Busca valor numa linha de CSV por nome de coluna, case-insensitive e
        tolerante a acentos/emojis (compara por substring normalizada)."""
        norm = {}
        for k, v in row.items():
            if k is None:
                continue
            norm[k.lower().strip()] = v if v is not None else ""
        # 1) match exato (case-insensitive)
        for a in aliases:
            if a in norm and norm[a].strip():
                return norm[a].strip()
        # 2) match por substring (ex: "📚 disciplina (edital)" contém "disciplina")
        for a in aliases:
            for k, v in norm.items():
                if a in k and v.strip():
                    return v.strip()
        return ""

    if filename.endswith(".csv"):
        # Auto-detectar delimitador: CSVs pt-BR (Excel) usam ';', outros usam ','
        sample = text[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
            delimiter = dialect.delimiter
        except csv.Error:
            # Fallback: se a primeira linha tem mais ';' que ',', usa ';'
            first_line = text.splitlines()[0] if text.splitlines() else ""
            delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        for row in reader:
            items.append({
                "pergunta": _pick(row, "pergunta", "front", "question"),
                "resposta": _pick(row, "resposta", "back", "answer"),
                "materia": _pick(row, "materia", "matéria", "disciplina", "subject"),
            })
    elif filename.endswith(".txt") or filename.endswith(".tsv"):
        # Formato Anki: TSV (pergunta<TAB>resposta)
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                pergunta = parts[0].replace("<br>", "\n").strip()
                resposta = parts[1].replace("<br>", "\n").strip()
                items.append({"pergunta": pergunta, "resposta": resposta})
            elif len(parts) == 1 and parts[0]:
                # Caso só tenha pergunta (sem tab)
                items.append({"pergunta": parts[0].strip(), "resposta": ""})
    else:
        # JSON
        try:
            data = json.loads(text)
            if isinstance(data, list):
                items = [{
                    "pergunta": d.get("pergunta", ""),
                    "resposta": d.get("resposta", ""),
                    "materia": d.get("materia", "") or d.get("disciplina", ""),
                } for d in data]
            else:
                raise HTTPException(status_code=400, detail="Formato inválido") from None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Arquivo JSON inválido") from None

    count = 0
    duplicados = 0
    max_por_dia = 20  # Limitar revisões por dia para não sobrecarregar

    def _dedup_key(pergunta: str, resposta: str) -> str:
        """Chave de deduplicação: pergunta+resposta normalizadas (trim + lower + espaços colapsados)."""
        import re
        p = re.sub(r"\s+", " ", pergunta).strip().lower()
        r = re.sub(r"\s+", " ", resposta).strip().lower()
        return f"{p}\x1f{r}"

    # Chaves já existentes no banco (por usuário) para evitar duplicidade em re-imports
    seen: set[str] = set()
    for row in conn.execute(
        "SELECT pergunta, resposta FROM flashcards WHERE user_id = ?", (user_id,)
    ).fetchall():
        seen.add(_dedup_key(row[0] or "", row[1] or ""))

    for i, item in enumerate(items):
        pergunta = sanitize_input((item.get("pergunta") or "").strip(), max_length=2000)
        resposta = sanitize_input((item.get("resposta") or "").strip(), max_length=5000)
        materia = sanitize_input((item.get("materia") or "").strip())
        if not pergunta:
            continue
        # Deduplicação: pula se já existe (no banco) ou repetido dentro do próprio arquivo
        key = _dedup_key(pergunta, resposta)
        if key in seen:
            duplicados += 1
            continue
        seen.add(key)
        # Distribuir datas: primeiros 20 para hoje, próximos 20 para amanhã, etc.
        dia_offset = count // max_por_dia
        revisao_date = (date.today() + timedelta(days=dia_offset)).isoformat()
        conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, materia, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id) VALUES (?, ?, ?, ?, 1, 2.5, 0, ?)",
            (pergunta, resposta, materia, revisao_date, user_id)
        )
        count += 1
    conn.commit()
    dias_distribuidos = (count // max_por_dia) + 1
    log.info(f"Flashcards imported: {count} items ({duplicados} duplicates skipped) distributed over {dias_distribuidos} days")
    return {"ok": True, "importados": count, "duplicados_ignorados": duplicados, "distribuidos_em_dias": dias_distribuidos}


# ============================================================
# HELPER: Build elaboration prompts inline (used by review endpoints)
# ============================================================

def _build_elaboration_prompts(pergunta: str, resposta: str, materia: str) -> list:
    """Generates 2-3 quick elaboration prompts for inline use in review responses."""
    materia_lower = materia.lower()
    prompts = [
        {"tipo": "por_que", "prompt": f"Por que \"{resposta}\" é verdade/correto?"},
        {"tipo": "exemplo_pratico", "prompt": f"Dê um exemplo prático onde isso se aplica."},
    ]
    # Add domain-specific prompt
    if any(j in materia_lower for j in ["direito", "lei", "penal", "civil", "constitucional", "administrativo", "tributário"]):
        prompts.append({"tipo": "fundamento_legal", "prompt": "Qual artigo/dispositivo legal fundamenta isso?"})
    elif any(e in materia_lower for e in ["matemática", "lógic", "contab", "estatística"]):
        prompts.append({"tipo": "metodo_alternativo", "prompt": "Resolva/explique usando outro método."})
    else:
        prompts.append({"tipo": "consequencia", "prompt": "Qual a consequência de violar/ignorar isso?"})
    return prompts


# ============================================================
# GET /api/flashcards/{id}/elaboration-prompts — Elaboration Prompts (A3)
# ============================================================

# Matérias jurídicas conhecidas
_MATERIAS_JURIDICAS = {
    "direito constitucional", "direito administrativo", "direito penal",
    "direito civil", "direito processual civil", "direito processual penal",
    "direito do trabalho", "direito tributário", "direito empresarial",
    "direito ambiental", "direito previdenciário", "legislação",
    "direito eleitoral", "direito internacional", "direitos humanos",
    "criminologia", "medicina legal", "ética profissional",
}

_MATERIAS_EXATAS = {
    "matemática", "raciocínio lógico", "estatística", "contabilidade",
    "matemática financeira", "informática", "tecnologia da informação",
}


@router.get("/api/flashcards/{id}/elaboration-prompts", summary="Prompts elaborativos",
            description="Gera prompts elaborativos contextuais para um flashcard, baseado na matéria e conteúdo.")
def get_elaboration_prompts(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera 3-4 prompts elaborativos contextuais para um flashcard."""
    row = conn.execute(
        "SELECT id, pergunta, resposta, materia FROM flashcards WHERE id = ? AND user_id = ?",
        (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Flashcard não encontrado")

    pergunta = row["pergunta"]
    resposta = row["resposta"]
    materia = (row["materia"] or "").strip()
    materia_lower = materia.lower()

    prompts = []

    # Tipo 1: Por que é verdade?
    prompts.append({
        "tipo": "por_que",
        "icone": "🤔",
        "prompt": f"Por que \"{resposta}\" é verdade/correto?",
        "instrucao": "Explique o fundamento lógico ou legal por trás da resposta.",
    })

    # Tipo 2: Diferenciação
    prompts.append({
        "tipo": "diferenciacao",
        "icone": "⚖️",
        "prompt": f"Como isso se diferencia de conceitos semelhantes na mesma área?",
        "instrucao": f"Compare com outro conceito de '{materia}' que poderia ser confundido.",
    })

    # Tipo 3: Exemplo prático
    prompts.append({
        "tipo": "exemplo_pratico",
        "icone": "💡",
        "prompt": f"Dê um exemplo prático onde \"{resposta}\" se aplica.",
        "instrucao": "Pense em uma situação real (caso concreto, jurisprudência, notícia) onde isso acontece.",
    })

    # Tipo 4: Consequência
    prompts.append({
        "tipo": "consequencia",
        "icone": "⚡",
        "prompt": f"Qual a consequência de violar/ignorar isso?",
        "instrucao": "O que acontece se essa regra/conceito for descumprido ou desconsiderado?",
    })

    # Prompts específicos para matérias jurídicas
    if materia_lower in _MATERIAS_JURIDICAS or any(j in materia_lower for j in ["direito", "lei", "penal", "civil", "constitucional"]):
        prompts.append({
            "tipo": "fundamento_legal",
            "icone": "📜",
            "prompt": "Qual artigo/dispositivo legal fundamenta essa resposta?",
            "instrucao": "Cite o artigo de lei, súmula ou jurisprudência que embasa o conceito.",
        })
        prompts.append({
            "tipo": "excecao",
            "icone": "🚫",
            "prompt": "Existe exceção a essa regra? Quando NÃO se aplica?",
            "instrucao": "Identifique situações em que a regra não vale ou é mitigada.",
        })

    # Prompts específicos para matérias exatas
    elif materia_lower in _MATERIAS_EXATAS or any(e in materia_lower for e in ["matemática", "lógic", "contab", "estatística"]):
        prompts.append({
            "tipo": "metodo_alternativo",
            "icone": "🔢",
            "prompt": "Resolva/explique usando outro método ou abordagem.",
            "instrucao": "Tente chegar ao mesmo resultado por um caminho diferente.",
        })
        prompts.append({
            "tipo": "simplificacao",
            "icone": "✂️",
            "prompt": "Simplifique: explique em uma frase curta e direta.",
            "instrucao": "Resuma o conceito core em no máximo 15 palavras.",
        })

    return {
        "flashcard_id": id,
        "pergunta": pergunta,
        "resposta": resposta,
        "materia": materia,
        "total_prompts": len(prompts),
        "prompts": prompts,
        "instrucao_geral": "Responda mentalmente ou por escrito. A elaboração ativa melhora a retenção em até 50%.",
    }

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
from utils import paginate, today_str, update_streak

router = APIRouter(prefix="", tags=["Flashcards"])


@router.get("/api/flashcards", summary="Listar flashcards", description="Lista todos os flashcards com paginação opcional e filtro por matéria")
def list_flashcards(materia: str = "", page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if materia:
        rows = conn.execute("SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia FROM flashcards WHERE materia = ? AND user_id = ?", (materia, user_id)).fetchall()
    else:
        rows = conn.execute("SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia FROM flashcards WHERE user_id = ?", (user_id,)).fetchall()
    items = [dict(r) for r in rows]
    return paginate(items, page, limit)


@router.get("/api/flashcards/materias", summary="Listar matérias dos flashcards")
def list_flashcards_materias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT materia, COUNT(*) as total FROM flashcards WHERE user_id = ? GROUP BY materia ORDER BY total DESC", (user_id,)).fetchall()
    return [{"materia": r[0] or "Sem matéria", "total": r[1]} for r in rows]


@router.get("/api/flashcards/today")
def get_flashcards_today(materia: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna flashcards pendentes com ordenação inteligente baseada em 6 técnicas
    de estudo com evidência científica (spaced practice, interleaving, desirable difficulty,
    retrieval practice, successive relearning, pre-testing effect).
    """
    from study_ordering import order_items_intelligently

    if materia:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia FROM flashcards WHERE proxima_revisao <= ? AND materia = ? AND user_id = ?",
            (today_str(), materia, user_id)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, materia FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
            (today_str(), user_id)
        ).fetchall()
    items = [dict(r) for r in rows]

    if not items:
        return []

    result = order_items_intelligently(
        items,
        materia_key="materia",
    )

    # Limpar campos internos
    for card in result:
        card.pop("_expanding_retrieval", None)

    return result


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
    conn.execute("UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ? WHERE id = ? AND user_id = ?",
                 (new_intervalo, proxima, id, user_id))
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
        "UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ?, easiness_factor = ?, repetitions = ? WHERE id = ? AND user_id = ?",
        (intervalo, proxima, round(ef, 4), reps, id, user_id)
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

    proxima = (date.today() + timedelta(days=output.interval)).isoformat()
    new_reps = reps + 1

    # Update flashcard with FSRS results
    try:
        conn.execute(
            """UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ?,
               stability = ?, difficulty = ?, fsrs_state = ?, repetitions = ?
               WHERE id = ? AND user_id = ?""",
            (output.interval, proxima, round(output.stability, 6),
             round(output.difficulty, 4), output.state, new_reps, id, user_id)
        )
    except Exception:
        # Fallback if FSRS columns don't exist - just update interval and next review
        conn.execute(
            "UPDATE flashcards SET intervalo_dias = ?, proxima_revisao = ? WHERE id = ? AND user_id = ?",
            (output.interval, proxima, id, user_id)
        )

    update_streak(conn, "flashcards_revisados", user_id=user_id)
    conn.commit()

    log.info(f"Flashcard FSRS review: id={id} rating={rating} S={output.stability:.4f} D={output.difficulty:.4f} I={output.interval}")

    # A3: Suggest elaboration when rating is low (FSRS rating 1 = Again, 2 = Hard)
    elaboration_suggested = rating <= 2
    result = {
        "id": id,
        "intervalo_dias": output.interval,
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
    """Aceita JSON, CSV (colunas: pergunta, resposta) ou Anki TSV (pergunta<TAB>resposta)"""
    content = file.file.read()
    text = content.decode("utf-8")
    items = []

    filename = file.filename or ""

    if filename.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            items.append({"pergunta": row.get("pergunta", ""), "resposta": row.get("resposta", "")})
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
                items = [{"pergunta": d.get("pergunta", ""), "resposta": d.get("resposta", "")} for d in data]
            else:
                raise HTTPException(status_code=400, detail="Formato inválido") from None
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Arquivo JSON inválido") from None

    count = 0
    max_por_dia = 20  # Limitar revisões por dia para não sobrecarregar
    for i, item in enumerate(items):
        pergunta = item.get("pergunta", "").strip()
        resposta = item.get("resposta", "").strip()
        if not pergunta:
            continue
        # Distribuir datas: primeiros 20 para hoje, próximos 20 para amanhã, etc.
        dia_offset = count // max_por_dia
        revisao_date = (date.today() + timedelta(days=dia_offset)).isoformat()
        conn.execute(
            "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, easiness_factor, repetitions, user_id) VALUES (?, ?, ?, 1, 2.5, 0, ?)",
            (pergunta, resposta, revisao_date, user_id)
        )
        count += 1
    conn.commit()
    dias_distribuidos = (count // max_por_dia) + 1
    log.info(f"Flashcards imported: {count} items distributed over {dias_distribuidos} days")
    return {"ok": True, "importados": count, "distribuidos_em_dias": dias_distribuidos}


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

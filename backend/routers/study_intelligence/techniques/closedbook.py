"""Closed-book antes de open-book — retrieval practice antes de consultar o material.

Evidência: Agarwal, Karpicke et al.; field experiment (Frontiers in Psychology, 2019)
mostrou que grupos que faziam prova de "livro fechado" retinham mais que os de
"livro aberto" — porque a tentativa de recall SEM consulta é retrieval practice.
Aqui, antes de liberar a leitura do material (PDF/teoria), o app oferece um prompt
de recall closed-book; só depois libera o open-book, e registra o fluxo.
"""

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from logger import log
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


@router.get(
    "/api/study-intelligence/closed-book",
    summary="Prompt closed-book antes de abrir o material",
    description="""Antes de liberar a leitura (open-book) de uma matéria/tópico, gera um prompt de
recall SEM consulta. O usuário tenta lembrar tudo que sabe; só então abre o material.
Retorna também âncoras (tópicos do edital / perguntas de flashcards) para guiar o recall.""",
)
def closed_book_prompt(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    if not materia.strip():
        raise HTTPException(status_code=400, detail="materia é obrigatória")

    # Âncoras de recall: tópicos do edital + perguntas de flashcards da matéria.
    ancoras = []
    edital_params = [user_id, materia]
    edital_q = "SELECT topico FROM edital WHERE user_id = ? AND materia = ? AND arquivado = 0"
    if topico:
        edital_q += " AND topico LIKE ?"
        edital_params.append(f"%{topico}%")
    edital_q += " ORDER BY RANDOM() LIMIT 4"
    for r in conn.execute(edital_q, edital_params).fetchall():
        if r["topico"]:
            ancoras.append({"tipo": "topico_edital", "texto": r["topico"]})

    fc = conn.execute(
        "SELECT pergunta FROM flashcards WHERE user_id = ? AND materia = ? ORDER BY RANDOM() LIMIT 3",
        (user_id, materia),
    ).fetchall()
    for r in fc:
        if r["pergunta"]:
            ancoras.append({"tipo": "flashcard", "texto": r["pergunta"]})

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "modo": "closed_book",
        "instrucao": "📕 LIVRO FECHADO: antes de abrir o material, tente lembrar TUDO que você já sabe sobre este tema. "
        "Escreva ou fale em voz alta. Só depois libere a leitura (open-book).",
        "ancoras": ancoras,
        "tecnica": "Closed-book antes de open-book (Agarwal/Karpicke; Frontiers 2019): a tentativa de recall "
        "sem consulta é retrieval practice e supera consultar o material diretamente.",
    }


@router.post(
    "/api/study-intelligence/closed-book/resultado",
    summary="Registrar tentativa closed-book e liberar open-book",
    description="""Registra a autoavaliação do recall closed-book (0-100) e marca que o usuário
está liberado para abrir o material. Retorna feedback conforme o quanto lembrou.""",
)
def closed_book_resultado(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    materia = str(body.get("materia", "")).strip()
    topico = str(body.get("topico", "")).strip()
    if not materia:
        raise HTTPException(status_code=400, detail="materia é obrigatória")

    auto_recall = body.get("auto_recall")
    if auto_recall is not None:
        try:
            auto_recall = max(0, min(100, int(auto_recall)))
        except (ValueError, TypeError):
            raise HTTPException(status_code=400, detail="auto_recall deve ser 0-100") from None

    cur = conn.execute(
        """
        INSERT INTO closed_book_log (user_id, materia, topico, auto_recall, abriu_material, created_at)
        VALUES (?, ?, ?, ?, 1, ?)
        """,
        (user_id, materia, topico, auto_recall, today_str()),
    )
    conn.commit()
    log.info(f"Closed-book registrado: user={user_id} materia={materia} recall={auto_recall}")

    if auto_recall is None:
        msg = "📖 Material liberado! Compare o que você lembrou com o conteúdo."
    elif auto_recall >= 70:
        msg = "🧠 Ótimo recall! Use a leitura para preencher as poucas lacunas restantes."
    elif auto_recall >= 40:
        msg = "👍 Recall parcial. A leitura agora vai fixar os pontos que você não lembrou."
    else:
        msg = "🎯 Muitas lacunas — perfeito para aprender! Seu cérebro está pronto para absorver a leitura."

    return {"id": cur.lastrowid, "ok": True, "open_book_liberado": True, "mensagem": msg}

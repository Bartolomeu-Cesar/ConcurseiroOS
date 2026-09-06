"""Elaborative Interrogation ENCADEADA — prompts 'por quê' aninhados.

A Elaborative Interrogation básica (POST /elaboration, encoding.py) grava UMA
elaboração. Esta versão gera uma CADEIA de perguntas 'por quê' aninhadas, levando o
estudante a aprofundar a explicação camada a camada (por que é verdade? e por que a
causa disso? …). Evidência: Elaborative Interrogation (Dunlosky et al., 2013) tem
utilidade moderada; o encadeamento força processamento mais profundo (deep encoding).

Read-only: gera os prompts. O usuário pode salvar cada resposta via o endpoint
existente POST /api/study-intelligence/elaboration.
"""

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db_session

router = APIRouter(prefix="", tags=["Study Intelligence"])


@router.get(
    "/api/study-intelligence/elaborative-chain",
    summary="Cadeia de 'por quê' (Elaborative Interrogation encadeada)",
    description="""Gera uma sequência aninhada de perguntas 'por quê' a partir de um conceito/tópico,
para aprofundar a compreensão camada a camada. Cada nível parte da resposta do
anterior. Read-only — os prompts guiam o estudo; salve as respostas via /elaboration.""",
)
def elaborative_chain(
    conceito: str,
    materia: str = "",
    profundidade: int = Query(4, ge=2, le=6),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    conceito = (conceito or "").strip()
    if not conceito:
        raise HTTPException(status_code=400, detail="conceito é obrigatório")

    # Cadeia de prompts aninhados. Cada nível referencia a resposta do anterior,
    # aprofundando de 'o que/por que' para 'implicações/exceções'.
    templates = [
        f"Por que '{conceito}' é verdade/existe? Explique o mecanismo ou fundamento.",
        "E por que ISSO (a causa que você deu acima) acontece? Vá uma camada mais fundo.",
        "Como isso se conecta com algo que você já sabe? Dê uma relação concreta.",
        "Em que situação isso NÃO valeria (exceção/limite)? Por quê?",
        "Se você tivesse que explicar a um leigo em uma frase, qual seria — e por quê essa?",
        "Que consequência prática decorre disso para resolver uma questão de prova?",
    ]
    niveis = []
    for i in range(profundidade):
        niveis.append(
            {
                "nivel": i + 1,
                "prompt": templates[i],
                "instrucao": "Responda com suas palavras antes de ver o próximo 'por quê'.",
            }
        )

    # Âncora opcional: um flashcard/tópico do edital relacionado, para dar contexto.
    ancora = None
    if materia:
        row = conn.execute(
            "SELECT topico FROM edital WHERE user_id = ? AND materia = ? AND arquivado = 0 "
            "AND topico LIKE ? ORDER BY RANDOM() LIMIT 1",
            (user_id, materia, f"%{conceito}%"),
        ).fetchone()
        if row and row["topico"]:
            ancora = {"tipo": "topico_edital", "texto": row["topico"]}

    return {
        "conceito": conceito,
        "materia": materia or "(geral)",
        "profundidade": profundidade,
        "ancora": ancora,
        "niveis": niveis,
        "instrucao_geral": "Responda cada 'por quê' construindo sobre a resposta anterior. "
        "Parar de conseguir responder revela exatamente a lacuna a estudar.",
        "tecnica": "Elaborative Interrogation encadeada (Dunlosky 2013): perguntar 'por quê' repetidamente "
        "força processamento profundo e expõe lacunas de compreensão.",
    }

"""Interpolated Testing — mini-testes de recall no MEIO de uma leitura longa.

Evidência: Szpunar, Khan & Schacter (2013) e afins — inserir perguntas curtas de
retrieval intercaladas durante uma sessão longa (ex.: leitura de PDF/vídeo) reduz o
mind-wandering, diminui a ansiedade e melhora a retenção do conteúdo SUBSEQUENTE
(não só do já testado). Distinto do pre-test (antes) e do forward-testing.

Este endpoint entrega 1-2 itens curtos de recall sob demanda, para o leitor de PDF
disparar a cada N páginas/minutos. Prioriza itens do próprio tópico em leitura.
"""

from deps import get_user_id
from fastapi import APIRouter, Depends, Query

from database import get_db_session

router = APIRouter(prefix="", tags=["Study Intelligence"])


@router.get(
    "/api/study-intelligence/interpolated-test",
    summary="Mini-teste interpolado durante leitura longa",
    description="""Retorna 1-2 itens curtos de recall (flashcard ou questão) para intercalar no
meio de uma sessão de leitura longa. Chame a cada N páginas/minutos no leitor.
Reduz mind-wandering e melhora a absorção do conteúdo que ainda será lido.""",
)
def interpolated_test(
    materia: str,
    topico: str = "",
    quantidade: int = Query(2, ge=1, le=3),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    itens = []

    # 1) Flashcards curtos da matéria/tópico (recall direto).
    fc_params = [user_id, materia]
    fc_q = "SELECT id, pergunta, resposta FROM flashcards WHERE user_id = ? AND materia = ?"
    if topico:
        fc_q += " AND (pergunta LIKE ? OR resposta LIKE ?)"
        fc_params.extend([f"%{topico}%", f"%{topico}%"])
    fc_q += " ORDER BY RANDOM() LIMIT ?"
    fc_params.append(quantidade)
    for f in conn.execute(fc_q, fc_params).fetchall():
        itens.append(
            {
                "tipo": "flashcard",
                "id": f["id"],
                "pergunta": f["pergunta"],
                "resposta": f["resposta"],
            }
        )

    # 2) Completar com questões curtas se faltar.
    faltam = quantidade - len(itens)
    if faltam > 0:
        q_params = [user_id, materia]
        q_q = (
            "SELECT id, enunciado, resposta_correta FROM questoes "
            "WHERE user_id = ? AND materia = ? AND resposta_correta != ''"
        )
        if topico:
            q_q += " AND topico = ?"
            q_params.append(topico)
        q_q += " ORDER BY RANDOM() LIMIT ?"
        q_params.append(faltam)
        for q in conn.execute(q_q, q_params).fetchall():
            enun = q["enunciado"] or ""
            itens.append(
                {
                    "tipo": "questao",
                    "id": q["id"],
                    "pergunta": (enun[:200] + "...") if len(enun) > 200 else enun,
                    "resposta": q["resposta_correta"],
                }
            )

    if not itens:
        return {
            "materia": materia,
            "topico": topico or "(geral)",
            "disponivel": False,
            "itens": [],
            "mensagem": f"Sem flashcards/questões de '{materia}' para intercalar. Continue a leitura.",
        }

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "disponivel": True,
        "itens": itens,
        "instrucao": "⏸️ Pausa de recall: responda DE MEMÓRIA antes de continuar a leitura.",
        "tecnica": "Interpolated Testing (Szpunar 2013): mini-testes no meio da leitura reduzem "
        "dispersão e melhoram a retenção do conteúdo seguinte.",
    }

"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException, Query

from database import get_db_session
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# RETRIEVAL PRACTICE FORÇADO — Roediger & Butler (2011)
# Recall ANTES de estudar = Testing Effect (+50% retenção vs reler)
# ============================================================


@router.get(
    "/api/study-intelligence/retrieval-warmup",
    summary="Retrieval Practice Warmup",
    description="""Gera 3-5 perguntas de recall rápido ANTES de estudar um tópico.
O Testing Effect (Roediger 2011) mostra que tentar lembrar ANTES de estudar:
- Ativa conhecimento prévio (schema activation)
- Identifica lacunas (direciona atenção durante estudo)
- Melhora retenção em 50% vs simplesmente reler
Deve ser chamado ao iniciar qualquer sessão de estudo.""",
)
def retrieval_warmup(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera perguntas de recall para warmup antes de estudar."""

    # 1. Buscar questões que o user JÁ RESPONDEU dessa matéria (recall de memória existente)
    params = [user_id, materia, user_id]
    filtro_topico = ""
    if topico:
        filtro_topico = "AND q.topico LIKE ?"
        params.insert(2, f"%{topico}%")

    # Priorizar questões que errou recentemente (successive relearning)
    erradas = conn.execute(
        f"""
        SELECT q.id, q.enunciado, q.resposta_correta, q.materia, q.topico, q.explicacao
        FROM questoes q
        JOIN questoes_respostas qr ON qr.questao_id = q.id AND qr.user_id = q.user_id
        WHERE q.user_id = ? AND q.materia = ? {filtro_topico}
        AND qr.acertou = 0
        AND q.id IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)
        ORDER BY qr.id DESC
        LIMIT 2
    """,
        params,
    ).fetchall()
    recall_questions = [dict(r) for r in erradas]

    # 2. Buscar flashcards da matéria como perguntas de recall
    fc_params = [user_id, materia]
    flashcards = conn.execute(
        """
        SELECT id, pergunta, resposta, materia
        FROM flashcards
        WHERE user_id = ? AND materia = ?
        ORDER BY CASE
            WHEN stability > 0 AND stability < 5 THEN 0
            WHEN repetitions = 0 THEN 2
            ELSE 1
        END, RANDOM()
        LIMIT 3
    """,
        fc_params,
    ).fetchall()

    recall_flashcards = [
        {
            "id": f["id"],
            "pergunta": f["pergunta"],
            "resposta": f["resposta"],
            "tipo": "flashcard_recall",
        }
        for f in flashcards
    ]

    # 3. Gerar perguntas abertas baseadas nos tópicos do edital
    topicos_edital = conn.execute(
        """
        SELECT topico FROM edital
        WHERE user_id = ? AND materia = ? AND arquivado = 0 AND status = 'Concluído'
        ORDER BY RANDOM() LIMIT 3
    """,
        (user_id, materia),
    ).fetchall()

    perguntas_abertas = [
        {
            "pergunta": f"O que você lembra sobre '{t['topico']}'? Liste os pontos principais.",
            "topico": t["topico"],
            "tipo": "recall_aberto",
        }
        for t in topicos_edital
    ]

    # Combinar: máx 5 itens (2 questões erradas + 2 flashcards + 1 aberta)
    warmup_items = []
    warmup_items.extend(
        [
            {
                "tipo": "questao_recall",
                "id": q["id"],
                "pergunta": q["enunciado"][:200] + "..." if len(q["enunciado"]) > 200 else q["enunciado"],
                "resposta": q["resposta_correta"],
                "explicacao": q.get("explicacao", ""),
            }
            for q in recall_questions[:2]
        ]
    )

    warmup_items.extend(recall_flashcards[:2])
    warmup_items.extend(perguntas_abertas[:1])

    # Se não tem nada (matéria nova), sugerir pre-test
    if not warmup_items:
        return {
            "materia": materia,
            "modo": "pre_test",
            "items": [],
            "mensagem": f"Primeira sessão de {materia}! Comece respondendo algumas questões para mapear seu nível.",
            "sugestao": "Use o Pre-Test ou responda 5-10 questões antes de começar a teoria.",
            "tecnica": "Pre-testing Effect (Richland 2009): responder perguntas ANTES de estudar o conteúdo ativa curiosidade e direciona atenção.",
        }

    return {
        "materia": materia,
        "topico": topico or "geral",
        "modo": "retrieval_warmup",
        "items": warmup_items[:5],
        "total_items": len(warmup_items),
        "instrucao": "⚡ ANTES de estudar, tente responder cada item DE MEMÓRIA. Não consulte. Errar aqui é BOM — direciona seu estudo.",
        "mensagem": f"Warmup de {materia}: tente lembrar antes de estudar!",
        "tecnica": "Testing Effect (Roediger 2011): recall ativo antes do estudo melhora retenção em ~50% vs reler passivamente. Errar no warmup aumenta atenção durante o estudo subsequente.",
    }


@router.post("/api/study-intelligence/retrieval-warmup/resultado", summary="Registrar resultado do warmup")
def retrieval_warmup_resultado(
    materia: str = Body(...),
    acertos: int = Body(0),
    total: int = Body(0),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra o resultado do warmup para tracking de progresso."""
    from datetime import datetime

    conn.execute(
        """
        INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at)
        VALUES (?, 0.05, ?, 'retrieval_warmup', ?, ?)
    """,
        (materia, today_str(), user_id, datetime.now().isoformat()),
    )
    conn.commit()
    pct = round(acertos / total * 100) if total > 0 else 0
    if pct >= 80:
        msg = "🧠 Excelente recall! Sua memória está forte nessa matéria."
    elif pct >= 50:
        msg = "👍 Recall parcial. O estudo de hoje vai reforçar os pontos fracos que você identificou."
    else:
        msg = "🎯 Muitas lacunas identificadas! Ótimo — agora seu cérebro está preparado para absorver o conteúdo."
    return {"ok": True, "pct_recall": pct, "mensagem": msg}


# ============================================================
# FREE RECALL (Brain Dump) — Ativa recall sem prompt
# ============================================================


@router.post(
    "/api/study-intelligence/brain-dump",
    summary="Salvar Brain Dump (Free Recall)",
    description="""Free Recall: o aluno escreve tudo que lembra de uma matéria/tópico sem consulta.
Evidência: Karpicke & Blunt (2011) — Free recall é tão eficaz quanto elaborated concept mapping
para retenção de longo prazo, e superior para inferências. Roediger & Karpicke (2006) — Testing
effect: tentar lembrar sem prompt consolida mais que reler.""",
)
def save_brain_dump(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Salva um brain dump e analisa gaps vs tópicos do edital.

    body: {materia, texto, topico (opcional)}
    Retorna: análise de cobertura (quais tópicos do edital foram mencionados e quais faltaram).
    """
    materia = body.get("materia", "").strip()
    texto = body.get("texto", "").strip()
    topico = body.get("topico", "").strip()

    if not materia or not texto:
        raise HTTPException(status_code=400, detail="Matéria e texto são obrigatórios")

    # Salvar no banco
    conn.execute(
        """
        INSERT INTO brain_dump_log (user_id, materia, topico, texto, palavras, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (user_id, materia, topico, texto, len(texto.split()), today_str()),
    )
    conn.commit()

    # Análise de gaps: buscar tópicos do edital dessa matéria
    topicos_edital = conn.execute(
        """
        SELECT topico FROM edital WHERE materia = ? AND user_id = ? AND arquivado = 0
    """,
        (materia, user_id),
    ).fetchall()

    topicos_nomes = [t[0].lower() for t in topicos_edital if t[0]]
    texto_lower = texto.lower()

    # Verificar quais tópicos foram mencionados
    mencionados = []
    nao_mencionados = []
    for t_nome in topicos_nomes:
        # Buscar palavras-chave do tópico no texto (tokenização simples)
        palavras_topico = [p for p in t_nome.split() if len(p) > 3]
        match_count = sum(1 for p in palavras_topico if p in texto_lower)
        if match_count >= max(1, len(palavras_topico) * 0.4):
            mencionados.append(t_nome)
        else:
            nao_mencionados.append(t_nome)

    cobertura_pct = (len(mencionados) / len(topicos_nomes) * 100) if topicos_nomes else 0

    return {
        "ok": True,
        "palavras_escritas": len(texto.split()),
        "analise": {
            "total_topicos_edital": len(topicos_nomes),
            "mencionados": len(mencionados),
            "nao_mencionados": len(nao_mencionados),
            "cobertura_pct": round(cobertura_pct, 1),
            "gaps": nao_mencionados[:10],  # Top 10 gaps
            "mencionados_lista": mencionados[:10],
        },
        "mensagem": (
            f"✅ Excelente! Você cobriu {round(cobertura_pct)}% dos tópicos."
            if cobertura_pct >= 70
            else f"⚠️ Gaps detectados: {len(nao_mencionados)} tópicos não mencionados. Revise-os!"
        ),
    }


@router.get(
    "/api/study-intelligence/brain-dump/historico",
    summary="Histórico de Brain Dumps",
    description="Lista brain dumps anteriores do usuário com análise de evolução.",
)
def brain_dump_historico(
    materia: str = "",
    limit: int = Query(10, ge=1, le=50),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna histórico de brain dumps com palavras e data."""
    params = [user_id]
    query = "SELECT id, materia, topico, palavras, created_at FROM brain_dump_log WHERE user_id = ?"
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    items = [dict(r) for r in rows]

    # Evolução: palavras escritas ao longo do tempo (mais palavras = mais recall)
    return {
        "items": items,
        "total": len(items),
        "evolucao": {
            "media_palavras": round(sum(i["palavras"] for i in items) / len(items)) if items else 0,
            "tendencia": "melhorando"
            if len(items) >= 2 and items[0]["palavras"] > items[-1]["palavras"]
            else "estável",
        },
    }

"""Judgment of Learning (JOL) preditivo — metacognição.

O usuário PREVÊ a probabilidade de lembrar um item no futuro (0-100%). Depois, o
resultado real é confrontado com a previsão para medir a calibração PREDITIVA —
distinta da calibração retrospectiva de /calibration (confiança na hora vs acerto).

Evidência: Judgments of Learning confrontados com desempenho real melhoram a
autorregulação e reduzem a "ilusão de competência" (Dunlosky & Metcalfe;
Rhodes & Tauber, 2011). Prever e depois ver o resultado calibra a metacognição.
"""

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from logger import log
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])

_TIPOS_VALIDOS = {"flashcard", "questao", "topico"}


@router.post(
    "/api/study-intelligence/jol",
    summary="Registrar previsão de aprendizado (JOL)",
    description="""Registra a PREVISÃO do usuário (0-100%) de que vai lembrar um item no futuro.
Item pode ser um flashcard, uma questão ou um tópico do edital. A previsão é depois
confrontada com o desempenho real (POST /jol/{id}/resultado) para medir calibração.""",
)
def registrar_jol(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    item_tipo = str(body.get("item_tipo", "")).strip().lower()
    item_ref = str(body.get("item_ref", "")).strip()
    materia = str(body.get("materia", "")).strip()
    predicao = body.get("predicao")

    if item_tipo not in _TIPOS_VALIDOS:
        raise HTTPException(status_code=400, detail=f"item_tipo deve ser um de: {sorted(_TIPOS_VALIDOS)}")
    if predicao is None:
        raise HTTPException(status_code=400, detail="predicao (0-100) é obrigatória")
    try:
        predicao = int(predicao)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="predicao deve ser um número inteiro 0-100") from None
    predicao = max(0, min(100, predicao))

    cur = conn.execute(
        """
        INSERT INTO jol_predictions (user_id, item_tipo, item_ref, materia, predicao, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, item_tipo, item_ref, materia, predicao, today_str()),
    )
    conn.commit()
    log.info(f"JOL registrado: user={user_id} tipo={item_tipo} ref={item_ref} predicao={predicao}")
    return {"id": cur.lastrowid, "ok": True, "predicao": predicao}


@router.post(
    "/api/study-intelligence/jol/{jol_id}/resultado",
    summary="Confrontar previsão JOL com resultado real",
    description="""Registra o resultado real (acertou/errou) de um item previsto e calcula o
erro de calibração = |predicao/100 - resultado| * 100. Erro baixo = boa calibração.""",
)
def resolver_jol(
    jol_id: int,
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    row = conn.execute(
        "SELECT id, predicao, resultado FROM jol_predictions WHERE id = ? AND user_id = ?",
        (jol_id, user_id),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Previsão JOL não encontrada")

    acertou = body.get("acertou")
    if acertou is None:
        raise HTTPException(status_code=400, detail="acertou (true/false ou 1/0) é obrigatório")
    resultado = 1 if acertou in (True, 1, "1", "true", "True") else 0

    erro = abs(row["predicao"] / 100.0 - resultado) * 100.0

    conn.execute(
        """
        UPDATE jol_predictions
        SET resultado = ?, erro_calibracao = ?, resolved_at = ?
        WHERE id = ? AND user_id = ?
        """,
        (resultado, round(erro, 1), today_str(), jol_id, user_id),
    )
    conn.commit()

    # Feedback interpretativo da calibração pontual.
    if erro <= 20:
        feedback = "🎯 Boa calibração! Sua previsão bateu com o resultado."
    elif row["predicao"] >= 60 and resultado == 0:
        feedback = "⚠️ Overconfidence: você previu que lembraria, mas errou. Reforce a revisão deste item."
    elif row["predicao"] <= 40 and resultado == 1:
        feedback = "💡 Underconfidence: você acertou apesar de prever que esqueceria. Confie mais no seu preparo."
    else:
        feedback = "📊 Calibração moderada — continue registrando previsões para afinar sua metacognição."

    return {
        "ok": True,
        "predicao": row["predicao"],
        "resultado": resultado,
        "erro_calibracao": round(erro, 1),
        "feedback": feedback,
    }


@router.get(
    "/api/study-intelligence/jol/resumo",
    summary="Resumo da calibração preditiva (JOL)",
    description="""Agrega as previsões JOL confrontadas: erro médio de calibração, viés
(overconfidence vs underconfidence) e contagem de previsões pendentes.""",
)
def resumo_jol(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    resolvidas = conn.execute(
        """
        SELECT predicao, resultado, erro_calibracao
        FROM jol_predictions
        WHERE user_id = ? AND resultado IS NOT NULL
        """,
        (user_id,),
    ).fetchall()

    pendentes = conn.execute(
        "SELECT COUNT(*) FROM jol_predictions WHERE user_id = ? AND resultado IS NULL",
        (user_id,),
    ).fetchone()[0]

    total = len(resolvidas)
    if total == 0:
        return {
            "total_confrontadas": 0,
            "pendentes": pendentes,
            "erro_medio": None,
            "vies": "sem_dados",
            "mensagem": "Registre previsões (JOL) e confronte com os resultados para calibrar sua metacognição.",
        }

    erro_medio = round(sum(r["erro_calibracao"] or 0 for r in resolvidas) / total, 1)

    # Viés: média(predicao/100) - média(resultado). Positivo = overconfidence.
    media_pred = sum(r["predicao"] for r in resolvidas) / total / 100.0
    media_result = sum(r["resultado"] for r in resolvidas) / total
    vies_valor = round((media_pred - media_result) * 100, 1)
    if vies_valor > 10:
        vies = "overconfidence"
        mensagem = "⚠️ Tendência a superestimar sua retenção. Revise mais antes de confiar que domina."
    elif vies_valor < -10:
        vies = "underconfidence"
        mensagem = "💡 Você subestima seu preparo — acerta mais do que prevê. Confie no processo."
    else:
        vies = "calibrado"
        mensagem = "🎯 Metacognição bem calibrada! Suas previsões refletem seu desempenho real."

    return {
        "total_confrontadas": total,
        "pendentes": pendentes,
        "erro_medio": erro_medio,
        "vies": vies,
        "vies_valor": vies_valor,
        "mensagem": mensagem,
    }

"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from logger import log
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# GET /api/study-intelligence/pre-test — Quiz antes de estudar
# ============================================================


@router.get(
    "/api/study-intelligence/pre-test",
    summary="Pre-Testing quiz",
    description="""Retorna questões rápidas sobre um tópico para o aluno responder ANTES de estudá-lo.
Pre-testing melhora retenção em 10-20% mesmo quando o aluno erra todas as questões,
pois ativa curiosidade e direciona a atenção durante o estudo subsequente.""",
)
def pre_test(
    materia: str,
    topico: str = "",
    quantidade: int = 3,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera um pre-test quiz para priming antes do estudo de um tópico."""

    # Buscar questões do banco sobre essa matéria/tópico que o usuário NÃO respondeu ainda
    params = [user_id, materia]
    query = """
        SELECT q.id, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c, q.alternativa_d,
               q.resposta_correta, q.topico, q.materia
        FROM questoes q
        WHERE q.user_id = ? AND q.materia = ?
        AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)
    """
    params.append(user_id)

    if topico:
        query += " AND q.topico = ?"
        params.append(topico)

    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(quantidade)

    questoes = conn.execute(query, params).fetchall()

    # Se não tem questões não-respondidas, pegar aleatórias da matéria (inclusive já respondidas)
    if len(questoes) < quantidade:
        fallback_query = """
            SELECT q.id, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c, q.alternativa_d,
                   q.resposta_correta, q.topico, q.materia
            FROM questoes q
            WHERE q.user_id = ? AND q.materia = ?
        """
        fallback_params = [user_id, materia]
        if topico:
            fallback_query += " AND q.topico = ?"
            fallback_params.append(topico)
        fallback_query += " ORDER BY RANDOM() LIMIT ?"
        fallback_params.append(quantidade)
        questoes = conn.execute(fallback_query, fallback_params).fetchall()

    if not questoes:
        return {
            "disponivel": False,
            "motivo": f"Sem questões de '{materia}' no banco. Adicione questões para ativar Pre-Testing.",
            "questoes": [],
        }

    return {
        "disponivel": True,
        "materia": materia,
        "topico": topico or "(geral)",
        "quantidade": len(questoes),
        "instrucao": "Responda sem medo de errar! O objetivo é ativar curiosidade e direcionar sua atenção. Errar aqui MELHORA sua aprendizagem depois.",
        "questoes": [
            {
                "id": q["id"],
                "enunciado": q["enunciado"],
                "alternativas": {
                    "A": q["alternativa_a"],
                    "B": q["alternativa_b"],
                    "C": q["alternativa_c"],
                    "D": q["alternativa_d"],
                },
                "resposta_correta": q["resposta_correta"],
            }
            for q in questoes
        ],
    }


# ============================================================
# POST /api/study-intelligence/self-explanation
# ============================================================


@router.post(
    "/api/study-intelligence/self-explanation",
    summary="Salvar self-explanation",
    description="Salva a explicação do aluno sobre por que errou uma questão. Técnica de Elaboration.",
)
def save_self_explanation(body: dict, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Salva auto-explicação para uma questão errada."""
    questao_id = body.get("questao_id")
    explicacao = body.get("explicacao", "").strip()

    if not questao_id or not explicacao:
        raise HTTPException(status_code=422, detail="questao_id e explicacao são obrigatórios")

    # Criar tabela se não existe
    conn.execute("""
        CREATE TABLE IF NOT EXISTS self_explanations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            questao_id INTEGER NOT NULL,
            explicacao TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_self_explanations_user ON self_explanations(user_id)
    """)

    conn.execute(
        "INSERT INTO self_explanations (user_id, questao_id, explicacao, created_at) VALUES (?, ?, ?, ?)",
        (user_id, questao_id, explicacao, today_str()),
    )
    conn.commit()

    log.info(f"Self-explanation saved: user={user_id} questao={questao_id} len={len(explicacao)}")
    return {"ok": True, "message": "Explicação salva com sucesso"}


# ============================================================
# GET /api/study-intelligence/calibration — Metacognition calibration data
# ============================================================


@router.get(
    "/api/study-intelligence/calibration",
    summary="Dados de calibração metacognitiva",
    description="Retorna dados de calibração: confiança vs acerto real ao longo do tempo.",
)
def get_calibration(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna métricas de calibração metacognitiva.

    Calibração perfeita = quando diz 80% confiante, acerta 80% das vezes.
    Overconfidence = confiança > acerto real.
    Underconfidence = confiança < acerto real.
    """
    # Get flashcard review history with FSRS quality (as proxy for accuracy)
    # We use streaks and question responses to build calibration data
    hoje = date.today()
    trinta_dias = (hoje - timedelta(days=30)).isoformat()

    # Question accuracy by day (last 30 days)
    daily_stats = conn.execute(
        """
        SELECT data, COUNT(*) as total, SUM(acertou) as acertos,
               ROUND(CAST(SUM(acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto
        FROM questoes_respostas
        WHERE user_id = ? AND data >= ?
        GROUP BY data ORDER BY data
    """,
        (user_id, trinta_dias),
    ).fetchall()

    # Overall calibration metrics
    total_respostas = sum(r["total"] for r in daily_stats) if daily_stats else 0
    total_acertos = sum(r["acertos"] for r in daily_stats) if daily_stats else 0
    accuracy_real = round(total_acertos / total_respostas * 100, 1) if total_respostas > 0 else 0

    # Flashcard quality distribution (proxy for how well user knows material)
    try:
        flash_quality = conn.execute(
            """
            SELECT easiness_factor, COUNT(*) as cnt
            FROM flashcards
            WHERE user_id = ? AND easiness_factor > 0
            GROUP BY ROUND(easiness_factor, 1)
            ORDER BY easiness_factor
        """,
            (user_id,),
        ).fetchall()
    except Exception:
        flash_quality = []

    # Improvement trend (comparing first half vs second half of period)
    mid_date = (hoje - timedelta(days=15)).isoformat()
    first_half = [r for r in daily_stats if r["data"] < mid_date]
    second_half = [r for r in daily_stats if r["data"] >= mid_date]

    first_pct = (
        round(sum(r["acertos"] for r in first_half) / max(1, sum(r["total"] for r in first_half)) * 100, 1)
        if first_half
        else 0
    )
    second_pct = (
        round(sum(r["acertos"] for r in second_half) / max(1, sum(r["total"] for r in second_half)) * 100, 1)
        if second_half
        else 0
    )
    trend = round(second_pct - first_pct, 1)

    return {
        "periodo": f"{trinta_dias} a {hoje.isoformat()}",
        "metricas": {
            "total_respostas": total_respostas,
            "acuracia_real": accuracy_real,
            "tendencia_30d": trend,
            "tendencia_label": "melhorando" if trend > 2 else "estável" if abs(trend) <= 2 else "piorando",
        },
        "diario": [dict(r) for r in daily_stats],
        "flashcard_distribution": [{"ef": r["easiness_factor"], "count": r["cnt"]} for r in flash_quality],
        "dicas": _calibration_tips(accuracy_real, trend),
    }


def _calibration_tips(accuracy: float, trend: float) -> list:
    """Gera dicas personalizadas baseado na calibração."""
    tips = []
    if accuracy < 50:
        tips.append("📉 Acurácia abaixo de 50% — foque em menos matérias por vez e revise os fundamentos")
    elif accuracy < 70:
        tips.append("📊 Acurácia moderada — use o caderno de erros para revisitar questões erradas")
    else:
        tips.append("✅ Boa acurácia! Continue com a revisão espaçada para manter")

    if trend < -5:
        tips.append("⚠️ Tendência de queda — possível sobrecarga. Considere reduzir volume e aumentar qualidade")
    elif trend > 5:
        tips.append("🚀 Tendência de melhora — seu estudo está funcionando! Mantenha o ritmo")

    tips.append("🧠 Dica: use o slider de confiança nos flashcards para calibrar sua metacognição")
    return tips


# ============================================================
# GET /api/study-intelligence/overconfidence — Confidence-Based Repetition (A2)
# ============================================================


@router.get(
    "/api/study-intelligence/overconfidence",
    summary="Análise de overconfidence",
    description="""Identifica matérias onde o aluno tem ilusão de saber:
alta confiança mas baixo acerto. Overconfidence index > 20 = 'ilusão de saber'.""",
)
def overconfidence_analysis(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Calcula overconfidence por matéria: avg_confianca/3*100 - pct_acerto."""
    rows = conn.execute(
        """
        SELECT q.materia,
               COUNT(qr.id) as total_respostas,
               SUM(qr.acertou) as acertos,
               AVG(qr.confianca) as avg_confianca
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.confianca IS NOT NULL
        GROUP BY q.materia
        HAVING COUNT(qr.id) >= 5
        ORDER BY AVG(qr.confianca) DESC
    """,
        (user_id,),
    ).fetchall()

    materias = []
    for r in rows:
        total = r["total_respostas"]
        acertos = r["acertos"] or 0
        avg_conf = r["avg_confianca"] or 0
        pct_acerto = round(acertos / total * 100, 1) if total > 0 else 0
        confianca_pct = round(avg_conf / 3 * 100, 1)
        overconfidence_idx = round(confianca_pct - pct_acerto, 1)

        status = (
            "ilusão de saber"
            if overconfidence_idx > 20
            else (
                "calibrado"
                if abs(overconfidence_idx) <= 10
                else ("subconfiante" if overconfidence_idx < -10 else "leve overconfidence")
            )
        )

        sugestoes = []
        if overconfidence_idx > 20:
            sugestoes = [
                f"⚠️ Você marca alta confiança em {r['materia']} mas acerta apenas {pct_acerto}%",
                "📖 Revise os fundamentos desta matéria antes de avançar",
                "🔄 Use flashcards com revisão espaçada para consolidar",
                "❓ Resolva mais questões desta matéria com feedback detalhado",
            ]
        elif overconfidence_idx > 10:
            sugestoes = [
                f"📊 Confiança levemente acima do desempenho real em {r['materia']}",
                "🧪 Faça um mini-simulado focado nesta matéria para calibrar",
            ]
        elif overconfidence_idx < -10:
            sugestoes = [
                f"💪 Você sabe mais do que pensa em {r['materia']}! Acurácia: {pct_acerto}%",
                "🎯 Aumente a dificuldade — você está pronto para questões mais difíceis",
            ]

        materias.append(
            {
                "materia": r["materia"],
                "total_respostas": total,
                "pct_acerto": pct_acerto,
                "avg_confianca": round(avg_conf, 2),
                "confianca_pct": confianca_pct,
                "overconfidence_idx": overconfidence_idx,
                "status": status,
                "sugestoes": sugestoes,
            }
        )

    # Ordenar por maior overconfidence (top 5)
    materias.sort(key=lambda x: x["overconfidence_idx"], reverse=True)
    top5 = materias[:5]

    ilusoes = [m for m in materias if m["status"] == "ilusão de saber"]

    return {
        "total_materias_analisadas": len(materias),
        "ilusoes_de_saber": len(ilusoes),
        "alerta_geral": (
            f"🚨 Você tem {len(ilusoes)} matéria(s) com 'ilusão de saber' — priorize revisão!"
            if ilusoes
            else "✅ Sua autoavaliação está bem calibrada."
        ),
        "top5_overconfidence": top5,
        "todas_materias": materias,
        "dica_metodologica": "Marque sua confiança (1-3) ao responder questões para melhorar a calibração metacognitiva.",
    }

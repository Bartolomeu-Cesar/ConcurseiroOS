"""
Router de Inteligência de Estudo — Técnicas modernas de aprendizagem.

Implementa:
1. Difficulty Score por tópico (ponderado por erros, tempo, recência)
2. Retrieval Strength (força de memória baseado em FSRS)
3. Interleaving inteligente (ordem de estudo otimizada)
4. Desirable Difficulty (nível de desafio ideal por matéria)
5. Knowledge Decay Prediction (previsão de esquecimento)
"""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# CONSTANTS
# ============================================================

# Weights for difficulty score calculation
W_ERROR_RATE = 0.40      # Peso da taxa de erro
W_RESPONSE_TIME = 0.20   # Peso do tempo de resposta (lento = difícil)
W_RECENCY = 0.15         # Peso da recência do erro (erros recentes pesam mais)
W_REPETITION = 0.15      # Peso de quantas vezes errou o mesmo tópico
W_FLASHCARD_FAIL = 0.10  # Peso dos flashcards com rating baixo nesse tópico

# Forgetting curve constants (baseado em Ebbinghaus + FSRS)
DECAY_BASE = 0.9         # Retenção inicial após revisão
STABILITY_FACTOR = 19    # Fator FSRS para conversão stability → days


# ============================================================
# GET /api/study-intelligence — Análise completa de aprendizagem
# ============================================================

@router.get("/api/study-intelligence", summary="Inteligência de estudo",
            description="""Retorna análise completa de aprendizagem com:
- Difficulty Score por tópico (0-100, quanto maior = mais difícil para você)
- Retrieval Strength (0-100, quanto menor = mais precisa revisar)
- Recomendações de interleaving (ordem otimizada de estudo)
- Previsão de esquecimento (topics at risk)
- Nível de desafio desejável (desirable difficulty)""")
def study_intelligence(
    limit: int = Query(20, description="Máximo de tópicos no resultado"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    hoje = date.today()
    trinta_dias = (hoje - timedelta(days=30)).isoformat()
    sete_dias = (hoje - timedelta(days=7)).isoformat()

    # ======= 1. DIFFICULTY SCORE POR TÓPICO =======
    # Fonte: questões respondidas (taxa de erro + tempo + recência)
    topic_stats = conn.execute("""
        SELECT q.materia, q.topico,
               COUNT(*) as total_respostas,
               SUM(CASE WHEN qr.acertou = 0 THEN 1 ELSE 0 END) as total_erros,
               AVG(qr.tempo_segundos) as avg_tempo,
               MAX(qr.data) as ultima_resposta,
               SUM(CASE WHEN qr.data >= ? AND qr.acertou = 0 THEN 1 ELSE 0 END) as erros_recentes,
               SUM(CASE WHEN qr.data >= ? AND qr.acertou = 1 THEN 1 ELSE 0 END) as acertos_recentes
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia, q.topico
        HAVING total_respostas >= 2
    """, (sete_dias, sete_dias, user_id)).fetchall()

    # Fonte: flashcards (ratings baixos indicam dificuldade)
    flash_difficulty = {}
    try:
        flash_rows = conn.execute("""
            SELECT materia, COUNT(*) as total,
                   SUM(CASE WHEN easiness_factor < 2.2 THEN 1 ELSE 0 END) as dificeis,
                   AVG(easiness_factor) as avg_ef
            FROM flashcards
            WHERE user_id = ? AND materia != ''
            GROUP BY materia
        """, (user_id,)).fetchall()
        for r in flash_rows:
            flash_difficulty[r["materia"]] = {
                "total": r["total"],
                "dificeis": r["dificeis"],
                "avg_ef": r["avg_ef"],
                "pct_dificil": round(r["dificeis"] / r["total"] * 100, 1) if r["total"] > 0 else 0
            }
    except Exception:
        pass

    # Calcular scores
    topics_scored = []
    avg_tempo_global = 45  # fallback

    # Calcular média global de tempo
    tempos = [r["avg_tempo"] for r in topic_stats if r["avg_tempo"]]
    if tempos:
        avg_tempo_global = sum(tempos) / len(tempos)

    for r in topic_stats:
        materia = r["materia"]
        topico = r["topico"] or "(geral)"
        total = r["total_respostas"]
        erros = r["total_erros"]

        # 1. Taxa de erro (normalizada 0-1)
        error_rate = erros / total if total > 0 else 0

        # 2. Tempo de resposta (normalizado: >média = mais difícil)
        avg_t = r["avg_tempo"] or avg_tempo_global
        tempo_score = min(1.0, avg_t / (avg_tempo_global * 2)) if avg_tempo_global > 0 else 0.5

        # 3. Recência (erros recentes pesam mais)
        erros_rec = r["erros_recentes"] or 0
        acertos_rec = r["acertos_recentes"] or 0
        recent_total = erros_rec + acertos_rec
        recency_score = (erros_rec / recent_total) if recent_total > 0 else error_rate

        # 4. Repetição de erros (errar muitas vezes o mesmo tópico)
        repetition_score = min(1.0, erros / 5)  # Saturação em 5 erros

        # 5. Flashcard difficulty para esta matéria
        flash_score = 0
        if materia in flash_difficulty:
            flash_score = flash_difficulty[materia]["pct_dificil"] / 100

        # Difficulty Score final (0-100)
        difficulty = round((
            W_ERROR_RATE * error_rate +
            W_RESPONSE_TIME * tempo_score +
            W_RECENCY * recency_score +
            W_REPETITION * repetition_score +
            W_FLASHCARD_FAIL * flash_score
        ) * 100, 1)

        # ======= 2. RETRIEVAL STRENGTH =======
        # Quanto tempo desde a última revisão correta?
        days_since = 0
        if r["ultima_resposta"]:
            try:
                ultima = date.fromisoformat(r["ultima_resposta"])
                days_since = (hoje - ultima).days
            except (ValueError, TypeError):
                days_since = 30

        # Modelo de esquecimento: R = e^(-t/S) onde S = stability
        # Estimamos stability baseado no histórico de acertos
        stability = max(1, (total - erros) * 2)  # Cada acerto contribui ~2 dias de stability
        # FSRS-5 power-law retrievability: R(t, S) = (1 + t/(9*S))^(-1)
        retrievability = (1.0 + days_since / (9.0 * max(stability, 0.01))) ** (-1) if stability > 0 else 0
        retrieval_strength = round(retrievability * 100, 1)

        # ======= 3. KNOWLEDGE DECAY — em risco de esquecer? =======
        at_risk = retrieval_strength < 50 and days_since > 3

        topics_scored.append({
            "materia": materia,
            "topico": topico,
            "difficulty_score": difficulty,
            "retrieval_strength": retrieval_strength,
            "days_since_review": days_since,
            "at_risk": at_risk,
            "stats": {
                "total_respostas": total,
                "total_erros": erros,
                "error_rate_pct": round(error_rate * 100, 1),
                "avg_tempo_s": round(avg_t, 1),
                "erros_recentes_7d": erros_rec,
            },
            # Desirable difficulty: se o tópico é "fácil demais", precisa de desafio maior
            "desirable_difficulty": _desirable_difficulty_label(difficulty, retrieval_strength),
        })

    # Sort: tópicos mais difíceis e em risco primeiro
    topics_scored.sort(key=lambda t: (t["difficulty_score"] * 0.6 + (100 - t["retrieval_strength"]) * 0.4), reverse=True)

    # ======= 4. INTERLEAVING RECOMMENDATIONS =======
    # Misturar matérias diferentes para melhor retenção
    interleaved_order = _generate_interleaved_order(topics_scored[:limit])

    # ======= 5. STUDY PLAN (prioridades para hoje) =======
    urgent = [t for t in topics_scored if t["at_risk"]][:5]
    hard = [t for t in topics_scored if t["difficulty_score"] >= 60][:5]
    review_needed = [t for t in topics_scored if t["retrieval_strength"] < 40][:5]

    # ======= 6. GLOBAL METRICS =======
    total_topics = len(topics_scored)
    avg_difficulty = round(sum(t["difficulty_score"] for t in topics_scored) / total_topics, 1) if total_topics > 0 else 0
    avg_retrieval = round(sum(t["retrieval_strength"] for t in topics_scored) / total_topics, 1) if total_topics > 0 else 100
    topics_at_risk = len([t for t in topics_scored if t["at_risk"]])

    return {
        "resumo": {
            "total_topicos_analisados": total_topics,
            "dificuldade_media": avg_difficulty,
            "retrieval_medio": avg_retrieval,
            "topicos_em_risco": topics_at_risk,
            "nivel_geral": _overall_level(avg_difficulty, avg_retrieval),
        },
        "prioridades": {
            "urgente_revisar": urgent,
            "mais_dificeis": hard,
            "memoria_fraca": review_needed,
        },
        "interleaving": interleaved_order,
        "topicos": topics_scored[:limit],
        "tecnicas_ativas": [
            "FSRS (Free Spaced Repetition Scheduler)",
            "Interleaving (mistura de tópicos)",
            "Desirable Difficulty (dificuldade desejável)",
            "Retrieval Practice (prática de recuperação)",
            "Elaborative Interrogation (caderno de erros)",
            "Spaced Practice (revisão espaçada)",
        ],
    }


# ============================================================
# GET /api/study-intelligence/next-review — O que revisar agora
# ============================================================

@router.get("/api/study-intelligence/next-review", summary="Próxima revisão inteligente",
            description="Retorna os tópicos que devem ser revisados agora, priorizados por urgência.")
def next_review(
    quantidade: int = Query(5, description="Número de itens para revisar"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna uma lista priorizada de o que revisar agora, combinando:
    - Flashcards com proxima_revisao <= hoje
    - Tópicos do edital em risco de esquecimento
    - Questões do caderno de erros pendentes
    """
    hoje = today_str()
    items = []

    # 1. Flashcards pendentes (ordenados por atraso)
    try:
        flashcards = conn.execute("""
            SELECT id, pergunta, resposta, materia, proxima_revisao, intervalo_dias, easiness_factor
            FROM flashcards
            WHERE proxima_revisao <= ? AND user_id = ?
            ORDER BY proxima_revisao ASC
            LIMIT ?
        """, (hoje, user_id, quantidade * 2)).fetchall()

        for f in flashcards:
            days_overdue = 0
            try:
                days_overdue = (date.today() - date.fromisoformat(f["proxima_revisao"])).days
            except (ValueError, TypeError):
                pass

            items.append({
                "tipo": "flashcard",
                "id": f["id"],
                "titulo": f["pergunta"][:80],
                "materia": f["materia"] or "Geral",
                "urgencia": min(100, 50 + days_overdue * 10),
                "motivo": f"Atrasado {days_overdue}d" if days_overdue > 0 else "Revisão hoje",
                "acao": f"/api/flashcards/{f['id']}/review-fsrs",
            })
    except Exception:
        pass

    # 2. Caderno de erros pendentes
    try:
        erros = conn.execute("""
            SELECT er.questao_id, er.proxima_revisao, er.intervalo_atual, er.revisoes_count,
                   q.materia, q.topico, q.enunciado
            FROM erros_revisao er
            JOIN questoes q ON q.id = er.questao_id
            WHERE er.proxima_revisao <= ? AND er.user_id = ?
            ORDER BY er.proxima_revisao ASC
            LIMIT ?
        """, (hoje, user_id, quantidade)).fetchall()

        for e in erros:
            days_overdue = 0
            try:
                days_overdue = (date.today() - date.fromisoformat(e["proxima_revisao"])).days
            except (ValueError, TypeError):
                pass

            items.append({
                "tipo": "erro_revisao",
                "id": e["questao_id"],
                "titulo": (e["enunciado"] or "")[:80],
                "materia": e["materia"] or "Geral",
                "urgencia": min(100, 60 + days_overdue * 8),
                "motivo": f"Erro revisão #{e['revisoes_count']+1} (intervalo: {e['intervalo_atual']}d)",
                "acao": f"/api/questoes/{e['questao_id']}",
            })
    except Exception:
        pass

    # 3. Tópicos do edital com revisão pendente
    try:
        topicos = conn.execute("""
            SELECT id, materia, topico, proxima_revisao, intervalo_revisao
            FROM edital
            WHERE proxima_revisao != '' AND proxima_revisao <= ? AND user_id = ? AND arquivado = 0
            ORDER BY proxima_revisao ASC
            LIMIT ?
        """, (hoje, user_id, quantidade)).fetchall()

        for t in topicos:
            days_overdue = 0
            try:
                days_overdue = (date.today() - date.fromisoformat(t["proxima_revisao"])).days
            except (ValueError, TypeError):
                pass

            items.append({
                "tipo": "topico_edital",
                "id": t["id"],
                "titulo": t["topico"] or t["materia"],
                "materia": t["materia"],
                "urgencia": min(100, 40 + days_overdue * 5),
                "motivo": f"Revisão espaçada (intervalo: {t['intervalo_revisao'] or 1}d)",
                "acao": f"/api/edital/{t['id']}/revisar-fsrs",
            })
    except Exception:
        pass

    # Sort by urgência (mais urgente primeiro)
    items.sort(key=lambda x: x["urgencia"], reverse=True)

    return {
        "total_pendente": len(items),
        "items": items[:quantidade],
        "mensagem": _review_message(len(items)),
    }


# ============================================================
# HELPERS
# ============================================================

def _desirable_difficulty_label(difficulty: float, retrieval: float) -> str:
    """Determina o nível de desafio ideal baseado no estado atual."""
    if difficulty >= 70:
        return "reduzir"  # Muito difícil — simplificar, usar mais exemplos
    elif difficulty >= 40 and retrieval >= 60:
        return "manter"  # Zona ideal — dificuldade desejável
    elif difficulty < 30 and retrieval > 80:
        return "aumentar"  # Muito fácil — precisa de desafio maior
    else:
        return "reforçar"  # Precisa de mais prática


def _overall_level(avg_difficulty: float, avg_retrieval: float) -> str:
    """Classificação geral do estudante."""
    if avg_retrieval >= 80 and avg_difficulty < 30:
        return "dominando"
    elif avg_retrieval >= 60:
        return "progredindo"
    elif avg_retrieval >= 40:
        return "consolidando"
    else:
        return "precisa_reforco"


def _generate_interleaved_order(topics: list) -> list:
    """Gera uma ordem de estudo com interleaving (evita estudar mesma matéria seguida).

    Interleaving melhora retenção em 20-40% vs. blocked practice.
    """
    if len(topics) <= 1:
        return [{"materia": t["materia"], "topico": t["topico"], "tipo": "estudo"} for t in topics]

    # Agrupar por matéria
    by_materia = {}
    for t in topics:
        mat = t["materia"]
        if mat not in by_materia:
            by_materia[mat] = []
        by_materia[mat].append(t)

    # Interleaving: alternar entre matérias diferentes
    result = []
    materias = list(by_materia.keys())
    mat_idx = 0
    max_rounds = len(topics)

    for _ in range(max_rounds):
        if not any(by_materia.values()):
            break
        # Encontrar próxima matéria com tópicos restantes
        attempts = 0
        while attempts < len(materias):
            mat = materias[mat_idx % len(materias)]
            mat_idx += 1
            if by_materia.get(mat):
                t = by_materia[mat].pop(0)
                result.append({
                    "materia": t["materia"],
                    "topico": t["topico"],
                    "difficulty_score": t["difficulty_score"],
                    "tipo": "reforco" if t["difficulty_score"] >= 50 else "revisao",
                })
                break
            attempts += 1

    return result


def _review_message(total: int) -> str:
    """Mensagem motivacional baseada na carga de revisão."""
    if total == 0:
        return "🎉 Tudo em dia! Nada para revisar agora."
    elif total <= 3:
        return "✨ Só alguns itens — revisão rápida!"
    elif total <= 10:
        return "📚 Sessão de revisão moderada. Foco!"
    elif total <= 20:
        return "💪 Bastante para revisar. Comece pelos urgentes."
    else:
        return "⚠️ Muitos itens acumulados. Priorize os 5 mais urgentes."


# ============================================================
# GET /api/study-intelligence/pre-test — Quiz antes de estudar
# ============================================================

@router.get("/api/study-intelligence/pre-test", summary="Pre-Testing quiz",
            description="""Retorna questões rápidas sobre um tópico para o aluno responder ANTES de estudá-lo.
Pre-testing melhora retenção em 10-20% mesmo quando o aluno erra todas as questões,
pois ativa curiosidade e direciona a atenção durante o estudo subsequente.""")
def pre_test(
    materia: str,
    topico: str = "",
    quantidade: int = 3,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
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
            "questoes": []
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

@router.post("/api/study-intelligence/self-explanation", summary="Salvar self-explanation",
             description="Salva a explicação do aluno sobre por que errou uma questão. Técnica de Elaboration.")
def save_self_explanation(
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Salva auto-explicação para uma questão errada."""
    questao_id = body.get("questao_id")
    explicacao = body.get("explicacao", "").strip()

    if not questao_id or not explicacao:
        from fastapi import HTTPException
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
        (user_id, questao_id, explicacao, today_str())
    )
    conn.commit()

    log.info(f"Self-explanation saved: user={user_id} questao={questao_id} len={len(explicacao)}")
    return {"ok": True, "message": "Explicação salva com sucesso"}


# ============================================================
# GET /api/study-intelligence/calibration — Metacognition calibration data
# ============================================================

@router.get("/api/study-intelligence/calibration", summary="Dados de calibração metacognitiva",
            description="Retorna dados de calibração: confiança vs acerto real ao longo do tempo.")
def get_calibration(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
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
    daily_stats = conn.execute("""
        SELECT data, COUNT(*) as total, SUM(acertou) as acertos,
               ROUND(CAST(SUM(acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto
        FROM questoes_respostas
        WHERE user_id = ? AND data >= ?
        GROUP BY data ORDER BY data
    """, (user_id, trinta_dias)).fetchall()

    # Overall calibration metrics
    total_respostas = sum(r["total"] for r in daily_stats) if daily_stats else 0
    total_acertos = sum(r["acertos"] for r in daily_stats) if daily_stats else 0
    accuracy_real = round(total_acertos / total_respostas * 100, 1) if total_respostas > 0 else 0

    # Flashcard quality distribution (proxy for how well user knows material)
    try:
        flash_quality = conn.execute("""
            SELECT easiness_factor, COUNT(*) as cnt
            FROM flashcards
            WHERE user_id = ? AND easiness_factor > 0
            GROUP BY ROUND(easiness_factor, 1)
            ORDER BY easiness_factor
        """, (user_id,)).fetchall()
    except Exception:
        flash_quality = []

    # Improvement trend (comparing first half vs second half of period)
    mid_date = (hoje - timedelta(days=15)).isoformat()
    first_half = [r for r in daily_stats if r["data"] < mid_date]
    second_half = [r for r in daily_stats if r["data"] >= mid_date]

    first_pct = round(sum(r["acertos"] for r in first_half) / max(1, sum(r["total"] for r in first_half)) * 100, 1) if first_half else 0
    second_pct = round(sum(r["acertos"] for r in second_half) / max(1, sum(r["total"] for r in second_half)) * 100, 1) if second_half else 0
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
# GET /api/study-intelligence/sleep-consolidation
# ============================================================

@router.get("/api/study-intelligence/sleep-consolidation", summary="Sleep consolidation check",
            description="""Verifica se é hora de uma sessão noturna ou revisão matinal.
Estudar antes de dormir + revisar ao acordar = +20% consolidação de memória.""")
def sleep_consolidation(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna recomendações de estudo baseadas no horário (consolidação durante sono)."""
    from datetime import datetime

    now = datetime.now()
    hora = now.hour

    # Determinar período do dia
    if 5 <= hora < 9:
        periodo = "matinal"
    elif 21 <= hora or hora < 1:
        periodo = "noturno"
    else:
        periodo = "diurno"

    # Buscar itens mais importantes para revisão rápida
    hoje = today_str()
    items_revisao = []

    if periodo in ("noturno", "matinal"):
        # Pegar flashcards mais difíceis revisados hoje (para consolidar)
        try:
            # Flashcards com EF baixo (difíceis) que foram revisados recentemente
            dificeis = conn.execute("""
                SELECT id, pergunta, resposta, materia
                FROM flashcards
                WHERE user_id = ? AND easiness_factor < 2.3 AND easiness_factor > 0
                ORDER BY easiness_factor ASC
                LIMIT 5
            """, (user_id,)).fetchall()
            for f in dificeis:
                items_revisao.append({
                    "tipo": "flashcard",
                    "id": f["id"],
                    "pergunta": f["pergunta"],
                    "materia": f["materia"] or "Geral",
                })
        except Exception:
            pass

        # Pegar questões erradas recentes (últimos 3 dias)
        try:
            erros_recentes = conn.execute("""
                SELECT q.id, q.enunciado, q.materia, q.resposta_correta
                FROM questoes_respostas qr
                JOIN questoes q ON q.id = qr.questao_id
                WHERE qr.user_id = ? AND qr.acertou = 0 AND qr.data >= ?
                ORDER BY qr.data DESC
                LIMIT 5
            """, (user_id, (date.today() - timedelta(days=3)).isoformat())).fetchall()
            for e in erros_recentes:
                items_revisao.append({
                    "tipo": "erro_recente",
                    "id": e["id"],
                    "pergunta": e["enunciado"][:100],
                    "materia": e["materia"] or "Geral",
                    "resposta_correta": e["resposta_correta"],
                })
        except Exception:
            pass

    mensagens = {
        "noturno": {
            "titulo": "🌙 Revisão Noturna (Sleep Consolidation)",
            "descricao": "Rever material difícil antes de dormir fortalece a consolidação durante o sono. Revise por 5-10 min sem pressão.",
            "dica": "Não precisa memorizar agora — apenas releia. Seu cérebro fará o trabalho durante a noite.",
        },
        "matinal": {
            "titulo": "☀️ Revisão Matinal (Morning Recall)",
            "descricao": "Tentar lembrar o que estudou ontem à noite ativa retrieval practice após consolidação do sono.",
            "dica": "Tente lembrar ANTES de olhar — o esforço de recuperação é o que fortalece a memória.",
        },
        "diurno": {
            "titulo": "📚 Sessão de Estudo Regular",
            "descricao": "Continue com sua rotina normal. Revisão noturna/matinal será sugerida nos horários ideais.",
            "dica": "Use interleaving: misture matérias diferentes para melhor retenção.",
        },
    }

    return {
        "periodo": periodo,
        "hora_atual": now.strftime("%H:%M"),
        "ativo": periodo in ("noturno", "matinal"),
        **mensagens[periodo],
        "items_revisao": items_revisao[:5],
        "total_items": len(items_revisao),
    }


# ============================================================
# GET /api/study-intelligence/contextual-variation — Mesmo tópico, formatos diferentes
# ============================================================

@router.get("/api/study-intelligence/contextual-variation", summary="Variação contextual",
            description="""Retorna o mesmo tópico em formatos diferentes para melhorar transferência.
Estudar o mesmo conceito como flashcard, questão, dissertativa e explicação oral
melhora a capacidade de aplicar o conhecimento em contextos novos.""")
def contextual_variation(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Gera variações de formato para um mesmo tópico."""
    variations = []

    # 1. Flashcard format (existe?)
    flash_query = "SELECT id, pergunta, resposta FROM flashcards WHERE user_id = ? AND materia = ?"
    flash_params = [user_id, materia]
    if topico:
        flash_query += " AND (pergunta LIKE ? OR resposta LIKE ?)"
        flash_params.extend([f"%{topico}%", f"%{topico}%"])
    flash_query += " ORDER BY RANDOM() LIMIT 2"
    flashcards = conn.execute(flash_query, flash_params).fetchall()
    for f in flashcards:
        variations.append({
            "formato": "flashcard",
            "icone": "🧠",
            "instrucao": "Tente responder mentalmente antes de revelar",
            "conteudo": {"pergunta": f["pergunta"], "resposta": f["resposta"]},
            "id": f["id"],
        })

    # 2. Questão format (existe?)
    q_query = "SELECT id, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, resposta_correta FROM questoes WHERE user_id = ? AND materia = ?"
    q_params = [user_id, materia]
    if topico:
        q_query += " AND topico = ?"
        q_params.append(topico)
    q_query += " ORDER BY RANDOM() LIMIT 2"
    questoes = conn.execute(q_query, q_params).fetchall()
    for q in questoes:
        variations.append({
            "formato": "questao",
            "icone": "❓",
            "instrucao": "Responda a questão objetiva",
            "conteudo": {
                "enunciado": q["enunciado"],
                "alternativas": {"A": q["alternativa_a"], "B": q["alternativa_b"], "C": q["alternativa_c"], "D": q["alternativa_d"]},
                "resposta": q["resposta_correta"],
            },
            "id": q["id"],
        })

    # 3. Dissertativa format (gerado)
    variations.append({
        "formato": "dissertativa",
        "icone": "✍️",
        "instrucao": "Escreva um parágrafo explicando este conceito com suas palavras",
        "conteudo": {
            "prompt": f"Explique com suas palavras o conceito de '{topico or materia}'. Use exemplos práticos.",
            "tempo_sugerido": "3-5 minutos",
        },
        "id": None,
    })

    # 4. Ensinar format (Feynman Technique)
    variations.append({
        "formato": "ensinar",
        "icone": "🎓",
        "instrucao": "Imagine que está ensinando isso a alguém que nunca estudou o tema. Explique em voz alta.",
        "conteudo": {
            "prompt": f"Ensine '{topico or materia}' como se estivesse explicando para um leigo. Se travar, identifique a lacuna.",
            "dica": "Se não conseguir explicar de forma simples, é sinal de que precisa revisar o fundamento.",
        },
        "id": None,
    })

    # 5. Mapa mental (connections)
    variations.append({
        "formato": "conexoes",
        "icone": "🔗",
        "instrucao": "Liste 3 conexões entre este tópico e outros que você já estudou",
        "conteudo": {
            "prompt": f"Como '{topico or materia}' se conecta com outros temas? Liste pelo menos 3 relações.",
            "exemplo": "Ex: 'Direito Penal > Princípio da Legalidade' se conecta com 'Direito Constitucional > Art. 5º' e com 'Direito Administrativo > Legalidade'",
        },
        "id": None,
    })

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "total_variacoes": len(variations),
        "instrucao_geral": "Estudar o mesmo conceito em formatos diferentes melhora a transferência de conhecimento. Complete pelo menos 3 variações.",
        "variacoes": variations,
    }


# ============================================================
# GET /api/study-intelligence/successive-relearning — Ciclos de re-aprendizagem
# ============================================================

@router.get("/api/study-intelligence/successive-relearning", summary="Successive Relearning",
            description="""Identifica tópicos que precisam de ciclos de re-aprendizagem.
Successive Relearning = retrieval practice + spaced repetition em ciclos:
Estudar → Testar → Espaçar → Re-testar → Espaçar mais → Re-testar...
Até atingir critério de domínio (3 acertos consecutivos).""")
def successive_relearning(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna tópicos que estão presos em baixo domínio e precisam de ciclos de re-learning."""
    hoje = date.today()
    trinta_dias = (hoje - timedelta(days=30)).isoformat()

    # Identificar tópicos com "stuck mastery": muitas tentativas mas acurácia não sobe
    stuck_topics = conn.execute("""
        SELECT q.materia, q.topico, COUNT(*) as total_tentativas,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto,
               MAX(qr.data) as ultima_tentativa,
               -- Calcular se os últimos 3 acertos foram consecutivos
               (SELECT COUNT(*) FROM (
                   SELECT acertou FROM questoes_respostas
                   WHERE questao_id IN (SELECT id FROM questoes WHERE materia = q.materia AND topico = q.topico AND user_id = ?)
                   AND user_id = ?
                   ORDER BY data DESC, id DESC LIMIT 3
               ) sub WHERE acertou = 1) as ultimos_3_acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ?
        GROUP BY q.materia, q.topico
        HAVING total_tentativas >= 4 AND pct_acerto < 70
        ORDER BY pct_acerto ASC
    """, (user_id, user_id, user_id, trinta_dias)).fetchall()

    cycles = []
    for t in stuck_topics:
        # Determine cycle stage
        acerto_pct = t["pct_acerto"]
        ultimos_3 = t["ultimos_3_acertos"] or 0
        total = t["total_tentativas"]

        if ultimos_3 >= 3:
            status = "dominado"
            proxima_acao = "Manter revisão espaçada normal"
            cor = "green"
        elif acerto_pct < 40:
            status = "re-estudar"
            proxima_acao = "Voltar ao material base. Releia e faça anotações antes de testar novamente."
            cor = "red"
        elif acerto_pct < 60:
            status = "praticar"
            proxima_acao = "Resolver mais questões variadas deste tópico. Foque na self-explanation."
            cor = "peach"
        else:
            status = "consolidar"
            proxima_acao = "Quase lá! Faça um teste final em 2-3 dias para fixar."
            cor = "yellow"

        days_since = 0
        try:
            days_since = (hoje - date.fromisoformat(t["ultima_tentativa"])).days
        except (ValueError, TypeError):
            pass

        cycles.append({
            "materia": t["materia"],
            "topico": t["topico"] or "(geral)",
            "status": status,
            "cor": cor,
            "pct_acerto": acerto_pct,
            "total_tentativas": total,
            "ultimos_3_acertos": ultimos_3,
            "dias_desde_ultima": days_since,
            "proxima_acao": proxima_acao,
            # Cycle info
            "ciclo_atual": 1 if acerto_pct < 40 else 2 if acerto_pct < 60 else 3,
            "ciclos_necessarios": 3,
            "criterio_dominio": "3 acertos consecutivos",
        })

    # Summary
    total_stuck = len(cycles)
    em_reestudo = len([c for c in cycles if c["status"] == "re-estudar"])
    em_pratica = len([c for c in cycles if c["status"] == "praticar"])
    em_consolidacao = len([c for c in cycles if c["status"] == "consolidar"])

    return {
        "total_topicos_stuck": total_stuck,
        "resumo": {
            "re_estudar": em_reestudo,
            "praticar": em_pratica,
            "consolidar": em_consolidacao,
        },
        "instrucao": "Successive Relearning: Para cada tópico abaixo, siga o ciclo Estudar → Testar → Espaçar → Re-testar até atingir 3 acertos consecutivos.",
        "ciclos": cycles[:15],
    }


# ============================================================
# GET /api/study-intelligence/dual-coding — Texto + Visual
# ============================================================

@router.get("/api/study-intelligence/dual-coding", summary="Dual Coding suggestions",
            description="""Sugere representações visuais para tópicos estudados.
Dual Coding: combinar informação verbal (texto) + visual (diagrama/imagem) cria 2 caminhos
independentes de memória, dobrando as chances de recall.""")
def dual_coding(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna sugestões de representação visual para um tópico."""

    # Templates de visualização por tipo de conteúdo
    visual_templates = {
        "processo": {
            "tipo": "fluxograma",
            "icone": "🔄",
            "instrucao": "Desenhe um fluxograma com as etapas em sequência. Use setas para indicar a ordem.",
            "exemplo": "Início → Petição → Citação → Contestação → Instrução → Sentença → Recurso",
        },
        "comparacao": {
            "tipo": "tabela_comparativa",
            "icone": "⚖️",
            "instrucao": "Crie uma tabela lado-a-lado comparando os conceitos similares.",
            "exemplo": "| Aspecto | Conceito A | Conceito B |\n|---------|-----------|------------|",
        },
        "hierarquia": {
            "tipo": "mapa_mental",
            "icone": "🌳",
            "instrucao": "Desenhe um mapa mental com o conceito central e ramificações.",
            "exemplo": "Tema central no meio → Subtemas em galhos → Detalhes nas folhas",
        },
        "timeline": {
            "tipo": "linha_do_tempo",
            "icone": "📅",
            "instrucao": "Organize os eventos/fatos em uma linha do tempo cronológica.",
            "exemplo": "1988 → CF | 1990 → CDC | 2002 → CC | 2015 → CPC",
        },
        "causa_efeito": {
            "tipo": "diagrama_causa_efeito",
            "icone": "🔀",
            "instrucao": "Desenhe causas à esquerda, efeitos à direita, conectados por setas.",
            "exemplo": "Causa 1 →\nCausa 2 → [Evento] → Consequência\nCausa 3 →",
        },
        "acronimo": {
            "tipo": "mnemônico_visual",
            "icone": "🎨",
            "instrucao": "Crie um acrônimo ou imagem mental associativa para memorizar a lista.",
            "exemplo": "LIMPE = Legalidade, Impessoalidade, Moralidade, Publicidade, Eficiência",
        },
    }

    # Detectar tipo de conteúdo baseado na matéria/tópico
    topico_lower = (topico or materia).lower()
    suggested_type = "hierarquia"  # default
    if any(w in topico_lower for w in ["processo", "procedimento", "fase", "etapa", "rito"]):
        suggested_type = "processo"
    elif any(w in topico_lower for w in ["diferença", "comparar", "versus", "vs", "distinção"]):
        suggested_type = "comparacao"
    elif any(w in topico_lower for w in ["história", "evolução", "cronolog", "constitui"]):
        suggested_type = "timeline"
    elif any(w in topico_lower for w in ["causa", "consequência", "efeito", "resultado"]):
        suggested_type = "causa_efeito"
    elif any(w in topico_lower for w in ["princípio", "requisito", "elemento", "espécie", "tipo", "modalidade"]):
        suggested_type = "acronimo"

    primary = visual_templates[suggested_type]

    # Buscar flashcards do tópico para sugerir o que visualizar
    content_items = []
    try:
        cards = conn.execute(
            "SELECT pergunta, resposta FROM flashcards WHERE user_id = ? AND materia = ? LIMIT 5",
            (user_id, materia)
        ).fetchall()
        content_items = [{"q": c["pergunta"], "a": c["resposta"]} for c in cards]
    except Exception:
        pass

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "sugestao_principal": {
            **primary,
            "materia": materia,
            "topico": topico,
        },
        "todas_opcoes": [
            {"tipo": v["tipo"], "icone": v["icone"], "instrucao": v["instrucao"]}
            for v in visual_templates.values()
        ],
        "conteudo_para_visualizar": content_items,
        "dica_geral": "Não precisa ser bonito! Um rabisco simples no papel ou um diagrama rápido já ativa o canal visual da memória. O importante é CRIAR, não copiar.",
    }


# ============================================================
# GET /api/study-intelligence/concrete-examples — Exemplos concretos
# ============================================================

@router.get("/api/study-intelligence/concrete-examples", summary="Concrete examples",
            description="""Gera exemplos concretos e analogias do mundo real para conceitos abstratos.
Exemplos concretos ancoram conceitos abstratos na memória de longo prazo.""")
def concrete_examples(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna exemplos concretos para um tópico (gerados por templates ou IA)."""

    # Base de exemplos por matéria (templates comuns para concursos)
    exemplos_base = {
        "Direito Constitucional": [
            {"conceito": "Princípio da Legalidade", "exemplo": "Um servidor público só pode fazer o que a lei autoriza. Se não há lei permitindo, está proibido. É como um cardápio: só pode pedir o que está escrito."},
            {"conceito": "Habeas Corpus", "exemplo": "João foi preso sem mandado e sem flagrante. Ele pode pedir HC para ser solto imediatamente — é como um 'botão de emergência' contra prisão ilegal."},
            {"conceito": "Cláusula Pétrea", "exemplo": "Imagine a Constituição como uma casa. As cláusulas pétreas são as vigas de sustentação — você pode reformar paredes (emendar), mas nunca mexer nas vigas."},
        ],
        "Direito Penal": [
            {"conceito": "Dolo Eventual", "exemplo": "Motorista bêbado: 'sei que posso matar alguém, mas tanto faz, vou dirigir assim mesmo'. Ele não QUER matar, mas ACEITA o risco."},
            {"conceito": "Culpa Consciente", "exemplo": "Malabarista com facas: 'sei que posso machucar alguém, mas confio na minha habilidade'. Ele prevê o risco mas acredita sinceramente que não vai acontecer."},
            {"conceito": "Legítima Defesa", "exemplo": "Ladrão armado invade sua casa. Você o empurra e ele cai. Usou força proporcional contra agressão injusta e atual — legítima defesa perfeita."},
        ],
        "Direito Administrativo": [
            {"conceito": "Impessoalidade", "exemplo": "Prefeito inaugura obra com placa 'Obra do Prefeito Silva'. ERRADO — a obra é do município, não da pessoa. É como um funcionário de banco: age em nome do banco, não dele."},
            {"conceito": "Discricionariedade", "exemplo": "Lei diz: 'prefeitura PODE construir praça'. O prefeito decide onde e quando. Mas se a lei diz 'DEVE construir', não tem escolha."},
        ],
    }

    # Buscar exemplos da base
    examples = exemplos_base.get(materia, [])

    # Se tem tópico específico, filtrar
    if topico and examples:
        filtered = [e for e in examples if topico.lower() in e["conceito"].lower()]
        if filtered:
            examples = filtered

    # Template para o aluno criar seus próprios exemplos
    create_template = {
        "instrucao": "Crie seu próprio exemplo concreto! Exemplos pessoais são mais memoráveis.",
        "formula": "Conceito abstrato → Situação do dia-a-dia que ilustra o conceito",
        "dicas": [
            "Use situações que você já viveu ou presenciou",
            "Quanto mais absurdo/engraçado, mais memorável",
            "Relacione com personagens de séries/filmes que você conhece",
            "Imagine explicando para uma criança de 10 anos",
        ],
    }

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "exemplos_prontos": examples[:5],
        "total_exemplos": len(examples),
        "criar_proprio": create_template,
        "por_que_funciona": "Exemplos concretos ativam mais áreas cerebrais que definições abstratas. Seu cérebro 'simula' a situação, criando memória episódica + semântica simultaneamente.",
    }


# ============================================================
# GET /api/study-intelligence/memory-palace — Palácio da Memória
# ============================================================

@router.get("/api/study-intelligence/memory-palace", summary="Memory Palace / Method of Loci",
            description="""Guia para criar um Palácio da Memória para listas e sequências.
O Method of Loci (Palácio da Memória) usa memória espacial para ancorar informações.
Ideal para: artigos de lei, princípios, listas de requisitos, prazos.""")
def memory_palace(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Guia para construir um Palácio da Memória para o tópico."""

    # Buscar items que são "listas" (princípios, requisitos, etc.)
    items_to_memorize = []
    try:
        # Flashcards dessa matéria que parecem ser listas
        cards = conn.execute("""
            SELECT pergunta, resposta FROM flashcards
            WHERE user_id = ? AND materia = ?
            AND (resposta LIKE '%,%,%' OR resposta LIKE '%1)%' OR resposta LIKE '%•%'
                 OR pergunta LIKE '%quais%' OR pergunta LIKE '%requisitos%'
                 OR pergunta LIKE '%princípios%' OR pergunta LIKE '%elementos%')
            LIMIT 5
        """, (user_id, materia)).fetchall()
        items_to_memorize = [{"pergunta": c["pergunta"], "resposta": c["resposta"]} for c in cards]
    except Exception:
        pass

    # Palácio template
    palace_template = {
        "nome": "Sua Casa",
        "locais": [
            {"posicao": 1, "local": "🚪 Porta de entrada", "dica": "Primeiro item da lista — visualize algo enorme bloqueando a porta"},
            {"posicao": 2, "local": "🛋️ Sala / Sofá", "dica": "Segundo item — imagine sentado no sofá fazendo algo absurdo"},
            {"posicao": 3, "local": "📺 TV / Estante", "dica": "Terceiro item — a TV está mostrando algo relacionado"},
            {"posicao": 4, "local": "🍳 Cozinha / Geladeira", "dica": "Quarto item — está dentro da geladeira, congelado"},
            {"posicao": 5, "local": "🚿 Banheiro", "dica": "Quinto item — visualize no espelho do banheiro"},
            {"posicao": 6, "local": "🛏️ Quarto / Cama", "dica": "Sexto item — está deitado na sua cama"},
            {"posicao": 7, "local": "🪟 Janela", "dica": "Sétimo item — está pendurado na janela"},
            {"posicao": 8, "local": "🚗 Garagem / Carro", "dica": "Oitavo item — está no banco do motorista"},
        ],
        "dicas_criacao": [
            "Use imagens ABSURDAS e EXAGERADAS (quanto mais ridículo, mais memorável)",
            "Ative os 5 sentidos: veja, ouça, sinta cheiro, toque, prove",
            "Faça os objetos interagirem com o local (não apenas 'colocados' lá)",
            "Percorra o palácio SEMPRE na mesma ordem",
            "Revise o percurso 3x: imediatamente, em 1h, e antes de dormir",
        ],
    }

    # Exemplo prático com conteúdo jurídico
    exemplo = {
        "topico": "Princípios da Administração Pública (LIMPE)",
        "palacio": [
            {"local": "Porta", "item": "Legalidade", "imagem": "Um juiz GIGANTE bloqueia a porta com um livro de leis. Você SÓ passa se mostrar a lei autorizando."},
            {"local": "Sala", "item": "Impessoalidade", "imagem": "Todas as pessoas no sofá estão sem rosto — são idênticas, impessoais."},
            {"local": "Cozinha", "item": "Moralidade", "imagem": "Sua avó está na cozinha olhando feio — ela julga se suas ações são morais."},
            {"local": "Banheiro", "item": "Publicidade", "imagem": "O espelho do banheiro é na verdade uma TV transmitindo tudo ao vivo para o público."},
            {"local": "Quarto", "item": "Eficiência", "imagem": "Um robô super-eficiente está arrumando seu quarto em 2 segundos."},
        ],
    }

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "palace_template": palace_template,
        "exemplo_pratico": exemplo,
        "items_para_memorizar": items_to_memorize,
        "ideal_para": [
            "Listas de princípios (LIMPE, contraditório, etc.)",
            "Artigos de lei e incisos",
            "Prazos processuais",
            "Requisitos de validade",
            "Sequências de fases/etapas",
        ],
        "ciencia": "O Method of Loci ativa o hipocampo (memória espacial + episódica). Campeões de memória usam esta técnica para memorizar 500+ dígitos em 5 minutos.",
    }


# ============================================================
# GET /api/study-intelligence/overconfidence — Confidence-Based Repetition (A2)
# ============================================================

@router.get("/api/study-intelligence/overconfidence", summary="Análise de overconfidence",
            description="""Identifica matérias onde o aluno tem ilusão de saber:
alta confiança mas baixo acerto. Overconfidence index > 20 = 'ilusão de saber'.""")
def overconfidence_analysis(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Calcula overconfidence por matéria: avg_confianca/3*100 - pct_acerto."""
    rows = conn.execute("""
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
    """, (user_id,)).fetchall()

    materias = []
    for r in rows:
        total = r["total_respostas"]
        acertos = r["acertos"] or 0
        avg_conf = r["avg_confianca"] or 0
        pct_acerto = round(acertos / total * 100, 1) if total > 0 else 0
        confianca_pct = round(avg_conf / 3 * 100, 1)
        overconfidence_idx = round(confianca_pct - pct_acerto, 1)

        status = "ilusão de saber" if overconfidence_idx > 20 else (
            "calibrado" if abs(overconfidence_idx) <= 10 else (
                "subconfiante" if overconfidence_idx < -10 else "leve overconfidence"
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

        materias.append({
            "materia": r["materia"],
            "total_respostas": total,
            "pct_acerto": pct_acerto,
            "avg_confianca": round(avg_conf, 2),
            "confianca_pct": confianca_pct,
            "overconfidence_idx": overconfidence_idx,
            "status": status,
            "sugestoes": sugestoes,
        })

    # Ordenar por maior overconfidence (top 5)
    materias.sort(key=lambda x: x["overconfidence_idx"], reverse=True)
    top5 = materias[:5]

    ilusoes = [m for m in materias if m["status"] == "ilusão de saber"]

    return {
        "total_materias_analisadas": len(materias),
        "ilusoes_de_saber": len(ilusoes),
        "alerta_geral": (
            f"🚨 Você tem {len(ilusoes)} matéria(s) com 'ilusão de saber' — priorize revisão!"
            if ilusoes else "✅ Sua autoavaliação está bem calibrada."
        ),
        "top5_overconfidence": top5,
        "todas_materias": materias,
        "dica_metodologica": "Marque sua confiança (1-3) ao responder questões para melhorar a calibração metacognitiva.",
    }


# ============================================================
# POST /api/study-intelligence/elaboration — Salvar elaboração (A3)
# ============================================================

@router.post("/api/study-intelligence/elaboration", summary="Salvar elaboration log",
             description="Registra a resposta do aluno a um prompt elaborativo.")
def save_elaboration(
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Grava na tabela elaboration_log.
    body: {flashcard_id ou questao_id, prompt_tipo, resposta_usuario}
    """
    flashcard_id = body.get("flashcard_id")
    questao_id = body.get("questao_id")
    prompt_tipo = body.get("prompt_tipo", "")
    resposta_usuario = body.get("resposta_usuario", "")

    if not prompt_tipo:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="prompt_tipo é obrigatório")

    conn.execute("""
        INSERT INTO elaboration_log (user_id, flashcard_id, questao_id, prompt_tipo, resposta_usuario, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, flashcard_id, questao_id, prompt_tipo, resposta_usuario, today_str()))
    conn.commit()

    return {"ok": True, "message": "Elaboração registrada com sucesso"}


# ============================================================
# BURNOUT DETECTION — Detecção de risco de esgotamento
# ============================================================

def _detect_burnout(conn, user_id: int) -> dict:
    """Detecta risco de burnout baseado em horas de estudo vs meta.

    Critérios:
    - horas > meta * 1.5 por 5+ dias consecutivos: risco moderado
    - horas > meta * 2.0 por 3+ dias consecutivos: risco alto
    """
    # Obter meta de horas
    metas = conn.execute("SELECT meta_horas FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    meta_horas = metas[0] if metas else 3.0

    # Obter últimos 7 dias de streaks
    sete_dias_atras = (date.today() - timedelta(days=6)).isoformat()
    rows = conn.execute("""
        SELECT data, horas_estudadas FROM streaks
        WHERE data >= ? AND user_id = ?
        ORDER BY data DESC
    """, (sete_dias_atras, user_id)).fetchall()

    if not rows:
        return {
            "risk": None,
            "dias_overwork": 0,
            "media_horas_7d": 0,
            "meta_horas": meta_horas,
            "sugestao": None,
        }

    # Calcular médias e dias de overwork
    horas_list = [r["horas_estudadas"] or 0 for r in rows]
    media_horas_7d = round(sum(horas_list) / len(horas_list), 1) if horas_list else 0

    # Checar dias consecutivos de overwork (do mais recente para trás)
    dias_overwork_150 = 0  # > meta * 1.5
    dias_overwork_200 = 0  # > meta * 2.0

    # Contar dias consecutivos acima de 1.5x
    for h in horas_list:
        if h > meta_horas * 1.5:
            dias_overwork_150 += 1
        else:
            break

    # Contar dias consecutivos acima de 2.0x
    for h in horas_list:
        if h > meta_horas * 2.0:
            dias_overwork_200 += 1
        else:
            break

    # Determinar nível de risco
    risk = None
    sugestao = None

    if dias_overwork_200 >= 3:
        risk = "alto"
        sugestao = "⚠️ Risco alto de burnout! Você está estudando mais que o dobro da meta há vários dias. Considere um dia de descanso completo ou reduza significativamente a carga."
    elif dias_overwork_150 >= 5:
        risk = "moderado"
        sugestao = "Considere um dia de descanso ativo ou redução de carga. Estudar demais pode prejudicar a retenção de longo prazo."
    elif dias_overwork_150 >= 3:
        risk = "moderado"
        sugestao = "Sua carga de estudo está elevada. Intercale dias mais leves para otimizar a consolidação de memória."

    return {
        "risk": risk,
        "dias_overwork": max(dias_overwork_150, dias_overwork_200),
        "media_horas_7d": media_horas_7d,
        "meta_horas": meta_horas,
        "sugestao": sugestao,
    }


@router.get("/api/study-intelligence/burnout", summary="Burnout Detection",
            description="Detecta risco de esgotamento baseado em padrão de horas de estudo vs meta configurada.")
def burnout_detection(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna análise de risco de burnout baseado nos últimos 7 dias."""
    return _detect_burnout(conn, user_id)


# ============================================================
# B2: FORGETTING CURVE VISUALIZER + PROACTIVE ALERTS
# ============================================================

# FSRS-5 retrievability formula: R(t, S) = (1 + t/(9*S))^(-1)
DESIRED_RETENTION = 0.9
REVIEW_TIME_FLASHCARD_MIN = 2
REVIEW_TIME_TOPICO_MIN = 5


def _calc_retrievability(elapsed_days: float, stability: float) -> float:
    """Calculate FSRS-5 retrievability: R = (1 + t/(9*S))^(-1)"""
    if stability <= 0:
        return 0.0
    return (1.0 + elapsed_days / (9.0 * stability)) ** (-1)


def _days_since_review(proxima_revisao: str, intervalo_dias: int, hoje: date) -> float:
    """Calculate days since last review based on proxima_revisao and interval.

    last_review = proxima_revisao - intervalo_dias
    days_since = hoje - last_review
    """
    if not proxima_revisao:
        return 0.0
    try:
        prox = date.fromisoformat(proxima_revisao)
        last_review = prox - timedelta(days=max(intervalo_dias or 1, 1))
        return max(0.0, (hoje - last_review).days)
    except (ValueError, TypeError):
        return 0.0


# ============================================================
# GET /api/study-intelligence/forgetting-curve
# ============================================================

@router.get("/api/study-intelligence/forgetting-curve",
            summary="Forgetting Curve Visualizer",
            description="""Gera curvas de esquecimento baseadas em FSRS-5 para visualização.
Retorna pontos de retenção projetados para os próximos 30 dias, agrupados por matéria.
Use para identificar quando a retenção cai abaixo do target (90%).""")
def forgetting_curve(
    materia: Optional[str] = Query(None, description="Filtrar por matéria específica"),
    topico_id: Optional[int] = Query(None, description="Filtrar por tópico do edital específico"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera curvas de esquecimento por matéria com projeção de 30 dias."""
    hoje = date.today()
    items = []  # List of dicts: {materia, stability, dias_desde_revisao, tipo}

    # --- 1. Query flashcards with stability > 0 ---
    fc_query = """
        SELECT id, materia, stability, proxima_revisao, intervalo_dias
        FROM flashcards
        WHERE user_id = ? AND stability > 0
    """
    fc_params = [user_id]

    if materia:
        fc_query += " AND materia = ?"
        fc_params.append(materia)

    flashcards = conn.execute(fc_query, fc_params).fetchall()
    for fc in flashcards:
        dias = _days_since_review(fc["proxima_revisao"], fc["intervalo_dias"], hoje)
        items.append({
            "materia": fc["materia"] or "Geral",
            "stability": fc["stability"],
            "dias_desde_revisao": dias,
            "tipo": "flashcard",
        })

    # --- 2. Query edital topics with stability_edital > 0 ---
    ed_query = """
        SELECT id, materia, topico, stability_edital, proxima_revisao, intervalo_revisao
        FROM edital
        WHERE user_id = ? AND stability_edital > 0 AND arquivado = 0
    """
    ed_params = [user_id]

    if topico_id:
        ed_query += " AND id = ?"
        ed_params.append(topico_id)
    elif materia:
        ed_query += " AND materia = ?"
        ed_params.append(materia)

    try:
        topicos = conn.execute(ed_query, ed_params).fetchall()
        for t in topicos:
            dias = _days_since_review(t["proxima_revisao"], t["intervalo_revisao"] if "intervalo_revisao" in t.keys() else 1, hoje)
            items.append({
                "materia": t["materia"] or "Geral",
                "stability": t["stability_edital"],
                "dias_desde_revisao": dias,
                "tipo": "topico",
            })
    except Exception:
        pass  # intervalo_revisao column might not exist in some setups

    if not items:
        return {
            "curvas": [],
            "desired_retention": DESIRED_RETENTION * 100,
            "total_items_analisados": 0,
            "mensagem": "Nenhum item com stability > 0 encontrado. Revise flashcards/tópicos para gerar curvas.",
        }

    # --- 3. Group by matéria ---
    materias_map: dict = {}
    for item in items:
        mat = item["materia"]
        if mat not in materias_map:
            materias_map[mat] = []
        materias_map[mat].append(item)

    # --- 4. Generate curves ---
    curvas = []

    # If materia was specified, return single aggregated curve
    # Otherwise, top 10 by item count
    if materia:
        materias_to_process = list(materias_map.keys())
    else:
        sorted_materias = sorted(materias_map.items(), key=lambda x: len(x[1]), reverse=True)
        materias_to_process = [m[0] for m in sorted_materias[:10]]

    for mat in materias_to_process:
        mat_items = materias_map[mat]
        stabilities = [i["stability"] for i in mat_items]
        stability_media = sum(stabilities) / len(stabilities)

        # Generate curve: for each day 0-30, calculate average retention
        pontos = []
        dia_critico = None

        for dia in range(31):
            retencoes = []
            for item in mat_items:
                # Total elapsed = dias_desde_revisao + dia (projection)
                elapsed = item["dias_desde_revisao"] + dia
                r = _calc_retrievability(elapsed, item["stability"])
                retencoes.append(r)

            avg_retencao = sum(retencoes) / len(retencoes)
            pontos.append({
                "dia": dia,
                "retencao": round(avg_retencao * 100, 1),
            })

            # Find critical day (first day below desired_retention)
            if dia_critico is None and avg_retencao < DESIRED_RETENTION:
                dia_critico = dia

        # Current retention (day 0)
        retencao_atual = pontos[0]["retencao"]

        curvas.append({
            "materia": mat,
            "stability_media": round(stability_media, 2),
            "retencao_atual": retencao_atual,
            "pontos": pontos,
            "dia_critico": dia_critico,
            "total_items": len(mat_items),
        })

    # Sort by lowest current retention (most at risk first)
    curvas.sort(key=lambda c: c["retencao_atual"])

    return {
        "curvas": curvas,
        "desired_retention": DESIRED_RETENTION * 100,
        "total_items_analisados": len(items),
    }


# ============================================================
# GET /api/study-intelligence/alerts
# ============================================================

@router.get("/api/study-intelligence/alerts",
            summary="Alertas proativos de esquecimento",
            description="""Identifica itens que cairão abaixo de 90% de retenção AMANHÃ.
Agrupa por matéria com urgência e tempo estimado de revisão.
Use para planejar sessões de revisão preventivas.""")
def forgetting_alerts(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna alertas proativos de itens em risco de esquecimento."""
    hoje = date.today()
    at_risk_items = []  # {materia, retencao_amanha, tipo}

    # --- 1. Flashcards com stability > 0 ---
    flashcards = conn.execute("""
        SELECT id, materia, stability, proxima_revisao, intervalo_dias
        FROM flashcards
        WHERE user_id = ? AND stability > 0
    """, (user_id,)).fetchall()

    for fc in flashcards:
        stability = fc["stability"]
        dias = _days_since_review(fc["proxima_revisao"], fc["intervalo_dias"], hoje)
        # Retention TOMORROW
        retencao_amanha = _calc_retrievability(dias + 1, stability)
        if retencao_amanha < DESIRED_RETENTION:
            at_risk_items.append({
                "materia": fc["materia"] or "Geral",
                "retencao_amanha": retencao_amanha,
                "tipo": "flashcard",
            })

    # --- 2. Edital topics com stability_edital > 0 ---
    try:
        topicos = conn.execute("""
            SELECT id, materia, stability_edital, proxima_revisao, intervalo_revisao
            FROM edital
            WHERE user_id = ? AND stability_edital > 0 AND arquivado = 0
        """, (user_id,)).fetchall()

        for t in topicos:
            stability = t["stability_edital"]
            intervalo = t["intervalo_revisao"] if "intervalo_revisao" in t.keys() else 1
            dias = _days_since_review(t["proxima_revisao"], intervalo, hoje)
            retencao_amanha = _calc_retrievability(dias + 1, stability)
            if retencao_amanha < DESIRED_RETENTION:
                at_risk_items.append({
                    "materia": t["materia"] or "Geral",
                    "retencao_amanha": retencao_amanha,
                    "tipo": "topico",
                })
    except Exception:
        pass

    if not at_risk_items:
        return {
            "alerts": [],
            "total_em_risco": 0,
            "tempo_total_min": 0,
            "mensagem": "✅ Nenhum item em risco de cair abaixo de 90% amanhã. Tudo sob controle!",
        }

    # --- 3. Group by matéria ---
    materias_map: dict = {}
    for item in at_risk_items:
        mat = item["materia"]
        if mat not in materias_map:
            materias_map[mat] = {"flashcards": 0, "topicos": 0, "retencoes": []}
        if item["tipo"] == "flashcard":
            materias_map[mat]["flashcards"] += 1
        else:
            materias_map[mat]["topicos"] += 1
        materias_map[mat]["retencoes"].append(item["retencao_amanha"])

    # --- 4. Build alerts ---
    alerts = []
    total_tempo = 0

    for mat, data in materias_map.items():
        n_flash = data["flashcards"]
        n_topico = data["topicos"]
        items_em_risco = n_flash + n_topico
        retencao_media = sum(data["retencoes"]) / len(data["retencoes"]) * 100
        tempo_revisao = n_flash * REVIEW_TIME_FLASHCARD_MIN + n_topico * REVIEW_TIME_TOPICO_MIN
        total_tempo += tempo_revisao

        # Urgência based on average retention
        if retencao_media < 70:
            urgencia = "alta"
        elif retencao_media < 80:
            urgencia = "media"
        else:
            urgencia = "baixa"

        alerts.append({
            "materia": mat,
            "items_em_risco": items_em_risco,
            "retencao_media": round(retencao_media, 1),
            "tempo_revisao_min": tempo_revisao,
            "urgencia": urgencia,
            "mensagem": f"{items_em_risco} itens de {mat} caem abaixo de 90% amanhã. ~{tempo_revisao}min de revisão.",
        })

    # Sort by urgency (alta first) then by items count
    urgencia_order = {"alta": 0, "media": 1, "baixa": 2}
    alerts.sort(key=lambda a: (urgencia_order.get(a["urgencia"], 3), -a["items_em_risco"]))

    return {
        "alerts": alerts,
        "total_em_risco": len(at_risk_items),
        "tempo_total_min": total_tempo,
    }


# ============================================================
# GET /api/study-intelligence/retention-summary
# ============================================================

@router.get("/api/study-intelligence/retention-summary",
            summary="Resumo de retenção geral",
            description="""Resumo geral de retenção: média hoje, projeções para 7 e 14 dias,
e contagem de itens abaixo do target agora vs. em 7 dias.""")
def retention_summary(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna resumo de retenção com projeções de 7 e 14 dias."""
    hoje = date.today()
    all_items = []  # {stability, dias_desde_revisao}

    # --- 1. Flashcards ---
    flashcards = conn.execute("""
        SELECT stability, proxima_revisao, intervalo_dias
        FROM flashcards
        WHERE user_id = ? AND stability > 0
    """, (user_id,)).fetchall()

    for fc in flashcards:
        dias = _days_since_review(fc["proxima_revisao"], fc["intervalo_dias"], hoje)
        all_items.append({
            "stability": fc["stability"],
            "dias_desde_revisao": dias,
        })

    # --- 2. Edital topics ---
    try:
        topicos = conn.execute("""
            SELECT stability_edital, proxima_revisao, intervalo_revisao
            FROM edital
            WHERE user_id = ? AND stability_edital > 0 AND arquivado = 0
        """, (user_id,)).fetchall()

        for t in topicos:
            intervalo = t["intervalo_revisao"] if "intervalo_revisao" in t.keys() else 1
            dias = _days_since_review(t["proxima_revisao"], intervalo, hoje)
            all_items.append({
                "stability": t["stability_edital"],
                "dias_desde_revisao": dias,
            })
    except Exception:
        pass

    if not all_items:
        return {
            "total_items": 0,
            "retencao_media_hoje": 0,
            "retencao_projecao_7d": 0,
            "retencao_projecao_14d": 0,
            "items_abaixo_target_hoje": 0,
            "items_abaixo_target_7d": 0,
            "desired_retention": DESIRED_RETENTION * 100,
            "mensagem": "Nenhum item com stability encontrado. Revise flashcards/tópicos para gerar dados.",
        }

    # --- 3. Calculate retention for today, +7d, +14d ---
    retencoes_hoje = []
    retencoes_7d = []
    retencoes_14d = []
    abaixo_hoje = 0
    abaixo_7d = 0

    for item in all_items:
        s = item["stability"]
        d = item["dias_desde_revisao"]

        r_hoje = _calc_retrievability(d, s)
        r_7d = _calc_retrievability(d + 7, s)
        r_14d = _calc_retrievability(d + 14, s)

        retencoes_hoje.append(r_hoje)
        retencoes_7d.append(r_7d)
        retencoes_14d.append(r_14d)

        if r_hoje < DESIRED_RETENTION:
            abaixo_hoje += 1
        if r_7d < DESIRED_RETENTION:
            abaixo_7d += 1

    avg_hoje = sum(retencoes_hoje) / len(retencoes_hoje) * 100
    avg_7d = sum(retencoes_7d) / len(retencoes_7d) * 100
    avg_14d = sum(retencoes_14d) / len(retencoes_14d) * 100

    # Trend analysis
    delta_7d = round(avg_7d - avg_hoje, 1)

    return {
        "total_items": len(all_items),
        "retencao_media_hoje": round(avg_hoje, 1),
        "retencao_projecao_7d": round(avg_7d, 1),
        "retencao_projecao_14d": round(avg_14d, 1),
        "items_abaixo_target_hoje": abaixo_hoje,
        "items_abaixo_target_7d": abaixo_7d,
        "desired_retention": DESIRED_RETENTION * 100,
        "tendencia_7d": delta_7d,
        "status": (
            "estável" if abs(delta_7d) <= 3
            else "em queda" if delta_7d < -3
            else "melhorando"
        ),
    }


# ============================================================
# #3 META ADAPTATIVA POR SEMANA
# ============================================================


@router.get("/api/metas/adaptativa", summary="Meta adaptativa baseada no ritmo real",
            description="Calcula meta semanal progressiva baseada no desempenho real. Inclui projeção de cobertura do edital e contagem regressiva até a prova.")
def meta_adaptativa(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Meta que se adapta ao ritmo real do aluno.

    Lógica:
    - Semana passada: média real de horas/questões/flashcards
    - Meta desta semana: +15% (progressão gradual)
    - Projeção: no ritmo atual, cobrirá X% do edital até a prova
    - Sugestão: para 100%, precisa aumentar para Y
    """
    from datetime import timedelta
    import re

    hoje = date.today()
    inicio_semana_passada = (hoje - timedelta(days=hoje.weekday() + 7)).isoformat()
    fim_semana_passada = (hoje - timedelta(days=hoje.weekday() + 1)).isoformat()
    inicio_esta_semana = (hoje - timedelta(days=hoje.weekday())).isoformat()

    # === Ritmo da semana passada ===
    horas_semana_passada = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ? AND data >= ? AND data <= ?",
        (user_id, inicio_semana_passada, fim_semana_passada)
    ).fetchone()[0]

    questoes_semana_passada = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ? AND data >= ? AND data <= ?",
        (user_id, inicio_semana_passada, fim_semana_passada)
    ).fetchone()[0]

    flashcards_semana_passada = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ? AND data >= ? AND data <= ?",
        (user_id, inicio_semana_passada, fim_semana_passada)
    ).fetchone()[0]

    # === Progresso desta semana (até agora) ===
    dias_passados_semana = hoje.weekday() + 1  # 1=seg, 7=dom
    horas_esta_semana = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ? AND data >= ?",
        (user_id, inicio_esta_semana)
    ).fetchone()[0]
    questoes_esta_semana = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ? AND data >= ?",
        (user_id, inicio_esta_semana)
    ).fetchone()[0]
    flashcards_esta_semana = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ? AND data >= ?",
        (user_id, inicio_esta_semana)
    ).fetchone()[0]

    # === Calcular meta adaptativa (+15% sobre semana passada, mínimo razoável) ===
    FATOR_PROGRESSAO = 1.15
    MIN_HORAS_SEMANA = 5.0
    MIN_QUESTOES_SEMANA = 20
    MIN_FLASHCARDS_SEMANA = 10

    meta_horas = max(MIN_HORAS_SEMANA, round(horas_semana_passada * FATOR_PROGRESSAO, 1))
    meta_questoes = max(MIN_QUESTOES_SEMANA, int(questoes_semana_passada * FATOR_PROGRESSAO))
    meta_flashcards = max(MIN_FLASHCARDS_SEMANA, int(flashcards_semana_passada * FATOR_PROGRESSAO))

    # === Projeção até a prova ===
    dias_prova = None
    semanas_restantes = None
    try:
        prova = conn.execute("""
            SELECT data_prova_objetiva FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?
            ORDER BY data_prova_objetiva LIMIT 1
        """, (user_id,)).fetchone()
        if prova and prova[0]:
            parts = re.match(r'(\d+)[/\-](\d+)[/\-](\d+)', prova[0])
            if parts:
                if len(parts.group(3)) == 4:
                    d = date(int(parts.group(3)), int(parts.group(2)), int(parts.group(1)))
                else:
                    d = date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
                dias_prova = max(0, (d - hoje).days)
                semanas_restantes = dias_prova // 7
    except Exception:
        pass

    # Cobertura do edital
    total_topicos = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE user_id = ? AND arquivado = 0 AND materia IN (SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?)",
        (user_id, user_id)
    ).fetchone()[0] or 1
    topicos_concluidos = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE user_id = ? AND arquivado = 0 AND status = 'Concluído' AND materia IN (SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?)",
        (user_id, user_id)
    ).fetchone()[0]
    pct_cobertura = round(topicos_concluidos / total_topicos * 100, 1)

    # Projeção: no ritmo atual, quantos tópicos cobrirá por semana?
    # Estimar: ~1 tópico por hora de estudo (simplificado)
    topicos_por_semana = max(1, round(horas_semana_passada * 1.0))
    topicos_restantes = total_topicos - topicos_concluidos

    if semanas_restantes and semanas_restantes > 0:
        topicos_projetados = topicos_por_semana * semanas_restantes
        cobertura_projetada = min(100, round((topicos_concluidos + topicos_projetados) / total_topicos * 100, 1))
        # Para 100%: horas necessárias por semana
        horas_para_100 = round(topicos_restantes / max(semanas_restantes, 1), 1) if topicos_restantes > 0 else 0
    else:
        cobertura_projetada = None
        horas_para_100 = None

    # === Motivação: comparar com meta ===
    pct_horas = round(horas_esta_semana / meta_horas * 100) if meta_horas > 0 else 0
    pct_questoes = round(questoes_esta_semana / meta_questoes * 100) if meta_questoes > 0 else 0
    pct_flashcards = round(flashcards_esta_semana / meta_flashcards * 100) if meta_flashcards > 0 else 0

    # Status motivacional
    if pct_horas >= 100 and pct_questoes >= 100:
        status = "acima"
        mensagem = "🚀 Acima da meta! Você está evoluindo rápido."
    elif pct_horas >= 70 or pct_questoes >= 70:
        status = "no_ritmo"
        mensagem = "👍 No ritmo! Continue assim até o final da semana."
    elif dias_passados_semana <= 2:
        status = "inicio"
        mensagem = "📅 Semana começando. Foco nas prioridades do dia!"
    else:
        status = "atras"
        mensagem = "⚠️ Abaixo do ritmo. Tente encaixar mais 30min hoje."

    return {
        "meta_semana": {
            "horas": meta_horas,
            "questoes": meta_questoes,
            "flashcards": meta_flashcards,
        },
        "progresso_semana": {
            "horas": round(horas_esta_semana, 2),
            "questoes": questoes_esta_semana,
            "flashcards": flashcards_esta_semana,
            "pct_horas": min(pct_horas, 100),
            "pct_questoes": min(pct_questoes, 100),
            "pct_flashcards": min(pct_flashcards, 100),
            "dias_passados": dias_passados_semana,
        },
        "semana_passada": {
            "horas": round(horas_semana_passada, 2),
            "questoes": questoes_semana_passada,
            "flashcards": flashcards_semana_passada,
        },
        "projecao": {
            "dias_prova": dias_prova,
            "semanas_restantes": semanas_restantes,
            "pct_cobertura_atual": pct_cobertura,
            "cobertura_projetada": cobertura_projetada,
            "horas_semana_para_100": horas_para_100,
            "topicos_restantes": topicos_restantes,
        },
        "status": status,
        "mensagem": mensagem,
        "fator_progressao": FATOR_PROGRESSAO,
    }


# ============================================================
# #4 DETECÇÃO DE PLATÔ E MUDANÇA DE ESTRATÉGIA
# ============================================================


@router.get("/api/inteligencia/plato", summary="Detectar platô e sugerir mudança",
            description="Analisa 3+ semanas de dados para detectar estagnação em matérias e sugere mudanças de abordagem (Bjork: desirable difficulties).")
def detectar_plato(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Detecta matérias estagnadas e sugere mudanças de estratégia.

    Platô = 2+ semanas sem melhora significativa (±3%) na taxa de acerto.
    Baseado em Bjork (2011): quando blocked practice para de funcionar,
    variar abordagem (interleaving, elaboration, generation) desbloqueio.
    """
    from datetime import timedelta

    hoje = date.today()
    platos = []

    # Buscar matérias do ciclo ativo
    ciclo_materias = conn.execute(
        "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
    ).fetchall()

    for mat_row in ciclo_materias:
        materia = mat_row["materia"]

        # Calcular % acerto por semana (últimas 4 semanas)
        semanas_data = []
        for weeks_ago in range(4):
            inicio = (hoje - timedelta(days=hoje.weekday() + 7 * weeks_ago + 7)).isoformat()
            fim = (hoje - timedelta(days=hoje.weekday() + 7 * weeks_ago + 1)).isoformat()

            stats = conn.execute("""
                SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
                FROM questoes_respostas qr
                JOIN questoes q ON q.id = qr.questao_id
                WHERE q.materia = ? AND qr.user_id = ? AND qr.data >= ? AND qr.data <= ?
            """, (materia, user_id, inicio, fim)).fetchone()

            total = stats["total"] or 0
            acertos = stats["acertos"] or 0
            pct = round((acertos / total * 100), 1) if total >= 3 else None  # Mínimo 3 questões para ser válido
            semanas_data.append({"semana": weeks_ago, "total": total, "pct": pct})

        # Detectar platô: 2+ semanas consecutivas com variação <= 3%
        semanas_validas = [s for s in semanas_data if s["pct"] is not None]
        if len(semanas_validas) < 2:
            continue

        # Comparar semanas mais recentes
        pcts = [s["pct"] for s in semanas_validas]
        variacao_max = max(pcts[:3]) - min(pcts[:3]) if len(pcts) >= 3 else max(pcts) - min(pcts)
        media_pct = round(sum(pcts) / len(pcts), 1)
        semanas_estagnado = 0

        for i in range(len(pcts) - 1):
            if abs(pcts[i] - pcts[i+1]) <= 3:
                semanas_estagnado += 1
            else:
                break

        is_plato = semanas_estagnado >= 2 and media_pct < 85

        if not is_plato:
            continue

        # Gerar sugestões de mudança de estratégia
        sugestoes = []

        # Analisar padrão de erros para sugestões específicas
        erros_topicos = conn.execute("""
            SELECT q.topico, COUNT(*) as erros FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE q.materia = ? AND qr.user_id = ? AND qr.acertou = 0
            AND qr.data >= ?
            GROUP BY q.topico ORDER BY erros DESC LIMIT 3
        """, (materia, user_id, (hoje - timedelta(days=21)).isoformat())).fetchall()

        topicos_fracos = [t["topico"] for t in erros_topicos if t["topico"]]

        if media_pct < 50:
            sugestoes.append({
                "tipo": "voltar_teoria",
                "titulo": "📖 Voltar à teoria",
                "descricao": f"Pare questões por 3 dias e estude os fundamentos. Seus erros concentram em: {', '.join(topicos_fracos[:2]) or 'tópicos básicos'}.",
                "prioridade": "alta",
            })
            sugestoes.append({
                "tipo": "elaboration",
                "titulo": "✍️ Técnica de Elaboração",
                "descricao": "Reescreva os conceitos com suas palavras. Ensine para alguém (ou escreva como se fosse ensinar).",
                "prioridade": "media",
            })
        elif media_pct < 70:
            sugestoes.append({
                "tipo": "interleaving",
                "titulo": "🔄 Mudar para Interleaving",
                "descricao": "Em vez de resolver só questões dessa matéria, misture com outras. O cérebro discrimina melhor assim.",
                "prioridade": "alta",
            })
            sugestoes.append({
                "tipo": "generation",
                "titulo": "🧠 Modo Generation",
                "descricao": "Tente responder questões SEM ver as alternativas primeiro. Gere a resposta mentalmente, depois confira.",
                "prioridade": "media",
            })
        else:
            sugestoes.append({
                "tipo": "desirable_difficulty",
                "titulo": "⬆️ Aumentar Dificuldade",
                "descricao": "Você domina o básico mas estagnou. Resolva questões de nível DIFÍCIL ou de bancas diferentes.",
                "prioridade": "alta",
            })
            sugestoes.append({
                "tipo": "simulado_parcial",
                "titulo": "📝 Simulado Cronometrado",
                "descricao": "Faça 20 questões dessa matéria em tempo de prova (30min). Pressão temporal revela gaps ocultos.",
                "prioridade": "media",
            })

        # Sempre sugerir análise de erros
        if topicos_fracos:
            sugestoes.append({
                "tipo": "foco_erros",
                "titulo": "🎯 Foco nos Erros",
                "descricao": f"Seus 3 tópicos mais errados: {', '.join(topicos_fracos)}. Estude APENAS eles por 2 dias.",
                "prioridade": "alta",
            })

        platos.append({
            "materia": materia,
            "media_pct": media_pct,
            "semanas_estagnado": semanas_estagnado + 1,
            "variacao": round(variacao_max, 1),
            "historico_semanas": semanas_validas,
            "topicos_fracos": topicos_fracos,
            "sugestoes": sugestoes,
        })

    # Ordenar: platô mais longo primeiro
    platos.sort(key=lambda x: (-x["semanas_estagnado"], x["media_pct"]))

    return {
        "platos_detectados": len(platos),
        "platos": platos,
        "mensagem": f"⚠️ {len(platos)} matéria{'s' if len(platos) != 1 else ''} em platô — hora de mudar a estratégia!" if platos else "✅ Nenhum platô detectado. Você está progredindo!",
    }

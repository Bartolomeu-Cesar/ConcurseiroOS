"""
Router de Inteligência de Estudo — Técnicas modernas de aprendizagem.

Implementa:
1. Difficulty Score por tópico (ponderado por erros, tempo, recência)
2. Retrieval Strength (força de memória baseado em FSRS)
3. Interleaving inteligente (ordem de estudo otimizada)
4. Desirable Difficulty (nível de desafio ideal por matéria)
5. Knowledge Decay Prediction (previsão de esquecimento)
"""
import math
from datetime import date, timedelta

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
        retrievability = math.exp(-days_since / stability) if stability > 0 else 0
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

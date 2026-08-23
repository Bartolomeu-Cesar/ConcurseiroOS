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

"""Router do Treinador Inteligente e Calendário Semanal.

Intelligence features:
1. Análise de padrão de erros (tópico-específico)
2. Ritmo adaptativo (horas/dia necessárias vs ritmo atual)
3. Curva de esquecimento personalizada (FSRS stability)
4. Distribuição por peso da banca (Raio-X frequency)
5. Detecção de platô (evolução estagnada)
6. Micro-metas dinâmicas (tópico mais fraco dentro da matéria)
7. Horário ótimo (baseado em padrões de estudo)
8. Sprint mode (< 30 dias = modo revisão intensiva)
"""
import math
import re
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, Query

from constants import WEIGHT_ACCURACY, WEIGHT_CONSISTENCY, WEIGHT_PROGRESS
from database import get_db_session
from deps import get_user_id
from logger import log
from utils import calculate_streak, today_str

router = APIRouter(prefix="", tags=["Treinador Inteligente"])


# ============================================================
# FUNÇÕES AUXILIARES — DADOS BASE
# ============================================================

def _get_performance_by_subject(conn, user_id: int) -> dict:
    rows = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
    """, (user_id,)).fetchall()
    return {r[0]: {"total": r[1], "acertos": r[2] or 0, "pct": round((r[2] or 0) / r[1] * 100, 1) if r[1] > 0 else 0} for r in rows}


def _get_last_session_by_subject(conn, user_id: int) -> dict:
    rows = conn.execute("SELECT materia, MAX(data) as ultima FROM sessoes_estudo WHERE user_id = ? GROUP BY materia", (user_id,)).fetchall()
    return {r[0]: r[1] for r in rows}


def _get_pending_reviews(conn, user_id: int) -> dict:
    flashcards = conn.execute("SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)).fetchone()[0]
    topicos = conn.execute("""
        SELECT COUNT(*) FROM edital WHERE proxima_revisao != '' AND proxima_revisao <= ? AND user_id = ?
    """, (today_str(), user_id)).fetchone()[0]
    return {"flashcards": flashcards, "topicos": topicos}


def _days_since_last_session(materia: str, ultima_sessao: dict, hoje: date) -> int:
    if materia in ultima_sessao and ultima_sessao[materia]:
        try:
            ultima = date.fromisoformat(ultima_sessao[materia])
            return (hoje - ultima).days
        except (ValueError, TypeError):
            pass
    return 0


# ============================================================
# INTELIGÊNCIA 1: ANÁLISE DE PADRÃO DE ERROS
# ============================================================

def _analyze_error_patterns(conn, user_id: int, limit: int = 5) -> list:
    """Identifica tópicos específicos com maior taxa de erro recente (últimos 30 dias)."""
    trinta_dias = (date.today() - timedelta(days=30)).isoformat()
    rows = conn.execute("""
        SELECT q.materia, q.topico, COUNT(*) as total,
               SUM(CASE WHEN qr.acertou = 0 THEN 1 ELSE 0 END) as erros,
               ROUND(CAST(SUM(CASE WHEN qr.acertou = 0 THEN 1 ELSE 0 END) AS REAL) / COUNT(*) * 100, 1) as pct_erro
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ?
        GROUP BY q.materia, q.topico
        HAVING total >= 3
        ORDER BY pct_erro DESC
        LIMIT ?
    """, (user_id, trinta_dias, limit)).fetchall()

    patterns = []
    for r in rows:
        if r["pct_erro"] >= 40:  # Só mostra se taxa de erro significativa
            patterns.append({
                "materia": r["materia"],
                "topico": r["topico"] or "(geral)",
                "total": r["total"],
                "erros": r["erros"],
                "pct_erro": r["pct_erro"],
                "sugestao": f"Resolver mais questões de {r['topico'] or r['materia']} ({r['pct_erro']}% de erro)"
            })
    return patterns


# ============================================================
# INTELIGÊNCIA 2: RITMO ADAPTATIVO
# ============================================================

def _calculate_adaptive_pace(conn, user_id: int, dias_prova: Optional[int],
                             edital_nome: str = "", cargo: str = "") -> Optional[dict]:
    """Calcula se o ritmo atual é suficiente para cobrir o edital antes da prova."""
    if dias_prova is None or dias_prova <= 0:
        return None

    # Tópicos pendentes
    query = "SELECT COUNT(*) FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    topicos_pendentes = conn.execute(query, params).fetchone()[0]

    if topicos_pendentes == 0:
        return {"status": "concluido", "msg": "Edital 100% concluído! Foque em revisão."}

    # Ritmo das últimas 4 semanas
    quatro_semanas = (date.today() - timedelta(days=28)).isoformat()
    horas_4sem = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND user_id = ?",
        (quatro_semanas, user_id)
    ).fetchone()[0]
    topicos_concluidos_4sem = conn.execute(
        "SELECT COUNT(DISTINCT data) FROM streaks WHERE data >= ? AND (horas_estudadas > 0) AND user_id = ?",
        (quatro_semanas, user_id)
    ).fetchone()[0]

    horas_por_dia_atual = horas_4sem / 28 if horas_4sem > 0 else 0
    topicos_por_dia_atual = (horas_4sem * 2) / 28  # ~2 tópicos/hora estimativa

    # Necessidade
    topicos_por_dia_necessario = topicos_pendentes / max(dias_prova, 1)
    horas_por_dia_necessario = topicos_por_dia_necessario / 2  # ~2 tópicos/hora

    deficit = horas_por_dia_necessario - horas_por_dia_atual
    pct_ritmo = (horas_por_dia_atual / horas_por_dia_necessario * 100) if horas_por_dia_necessario > 0 else 100

    if pct_ritmo >= 120:
        status = "acima"
        msg = f"✅ Ritmo excelente! {round(pct_ritmo)}% do necessário."
    elif pct_ritmo >= 80:
        status = "adequado"
        msg = f"👍 Ritmo adequado ({round(pct_ritmo)}%). Mantenha!"
    elif pct_ritmo >= 50:
        status = "insuficiente"
        msg = f"⚠️ Ritmo abaixo ({round(pct_ritmo)}%). Aumente para {round(horas_por_dia_necessario, 1)}h/dia."
    else:
        status = "critico"
        msg = f"🚨 Ritmo crítico ({round(pct_ritmo)}%). Precisa de {round(horas_por_dia_necessario, 1)}h/dia (atual: {round(horas_por_dia_atual, 1)}h)."

    return {
        "status": status,
        "msg": msg,
        "topicos_pendentes": topicos_pendentes,
        "dias_restantes": dias_prova,
        "horas_dia_atual": round(horas_por_dia_atual, 2),
        "horas_dia_necessario": round(horas_por_dia_necessario, 2),
        "pct_ritmo": round(pct_ritmo, 1),
        "deficit_diario": round(max(0, deficit), 2),
    }


# ============================================================
# INTELIGÊNCIA 3: CURVA DE ESQUECIMENTO (FSRS)
# ============================================================

def _get_forgetting_risk(conn, user_id: int, limit: int = 10) -> list:
    """Identifica tópicos/flashcards com maior risco de esquecimento baseado em FSRS stability."""
    hoje = today_str()
    at_risk = []

    # Flashcards com revisão atrasada e baixa stability
    try:
        flashcards = conn.execute("""
            SELECT id, pergunta, materia, stability, proxima_revisao,
                   julianday(?) - julianday(proxima_revisao) as dias_atraso
            FROM flashcards
            WHERE proxima_revisao <= ? AND user_id = ?
            ORDER BY stability ASC, dias_atraso DESC
            LIMIT ?
        """, (hoje, hoje, user_id, limit)).fetchall()

        for fc in flashcards:
            stability = fc["stability"] or 1.0
            dias_atraso = fc["dias_atraso"] or 0
            # Recall probability: R = e^(-t/S) where t=elapsed days, S=stability
            recall_prob = math.exp(-dias_atraso / max(stability, 0.1)) if dias_atraso > 0 else 0.9
            at_risk.append({
                "tipo": "flashcard",
                "id": fc["id"],
                "descricao": fc["pergunta"][:60],
                "materia": fc["materia"] or "",
                "stability": round(stability, 2),
                "dias_atraso": round(dias_atraso, 1),
                "recall_estimado": round(recall_prob * 100, 1),
                "urgencia": "critica" if recall_prob < 0.5 else "alta" if recall_prob < 0.7 else "media",
            })
    except Exception:
        pass  # stability columns might not exist

    # Tópicos do edital com baixa stability
    try:
        topicos = conn.execute("""
            SELECT id, materia, topico, stability_edital, proxima_revisao,
                   julianday(?) - julianday(proxima_revisao) as dias_atraso
            FROM edital
            WHERE proxima_revisao != '' AND proxima_revisao <= ? AND user_id = ? AND arquivado = 0
            ORDER BY stability_edital ASC
            LIMIT ?
        """, (hoje, hoje, user_id, limit)).fetchall()

        for t in topicos:
            stability = t["stability_edital"] or 1.0
            dias_atraso = t["dias_atraso"] or 0
            recall_prob = math.exp(-dias_atraso / max(stability, 0.1)) if dias_atraso > 0 else 0.9
            at_risk.append({
                "tipo": "topico",
                "id": t["id"],
                "descricao": f"{t['materia']}: {t['topico'][:40]}",
                "materia": t["materia"],
                "stability": round(stability, 2),
                "dias_atraso": round(dias_atraso, 1),
                "recall_estimado": round(recall_prob * 100, 1),
                "urgencia": "critica" if recall_prob < 0.5 else "alta" if recall_prob < 0.7 else "media",
            })
    except Exception:
        pass

    # Sort by urgency (lowest recall first)
    at_risk.sort(key=lambda x: x["recall_estimado"])
    return at_risk[:limit]


# ============================================================
# INTELIGÊNCIA 4: PESO DA BANCA (RAIO-X)
# ============================================================

def _get_banca_weights(conn, user_id: int, edital_nome: str = "", cargo: str = "") -> dict:
    """Obtém a distribuição de questões por matéria na banca alvo para priorização."""
    # Determinar banca do edital
    banca = ""
    if edital_nome:
        info = conn.execute(
            "SELECT banca FROM edital_info WHERE edital_nome = ? AND user_id = ? LIMIT 1",
            (edital_nome, user_id)
        ).fetchone()
        if info:
            banca = info["banca"] or ""

    if not banca:
        return {}

    # Frequência de questões por matéria nessa banca
    rows = conn.execute("""
        SELECT materia, COUNT(*) as freq
        FROM questoes WHERE banca = ? AND user_id = ?
        GROUP BY materia ORDER BY freq DESC
    """, (banca, user_id)).fetchall()

    if not rows:
        return {}

    total = sum(r["freq"] for r in rows)
    return {r["materia"]: {"freq": r["freq"], "peso_pct": round(r["freq"] / total * 100, 1)} for r in rows}


# ============================================================
# INTELIGÊNCIA 5: DETECÇÃO DE PLATÔ
# ============================================================

def _detect_plateaus(conn, user_id: int) -> list:
    """Detecta matérias onde o desempenho estagnou (sem melhoria em 2+ semanas)."""
    duas_semanas = (date.today() - timedelta(days=14)).isoformat()
    quatro_semanas = (date.today() - timedelta(days=28)).isoformat()

    # Performance nas últimas 2 semanas vs 2 semanas anteriores
    recent = conn.execute("""
        SELECT q.materia, COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ?
        GROUP BY q.materia HAVING total >= 5
    """, (user_id, duas_semanas)).fetchall()

    previous = conn.execute("""
        SELECT q.materia, COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ? AND qr.data < ?
        GROUP BY q.materia HAVING total >= 5
    """, (user_id, quatro_semanas, duas_semanas)).fetchall()

    prev_map = {r["materia"]: r["pct"] for r in previous}
    plateaus = []

    for r in recent:
        mat = r["materia"]
        pct_atual = r["pct"]
        pct_anterior = prev_map.get(mat)

        if pct_anterior is not None:
            delta = pct_atual - pct_anterior
            if abs(delta) <= 3 and pct_atual < 80:  # Estagnado e abaixo de 80%
                plateaus.append({
                    "materia": mat,
                    "pct_atual": pct_atual,
                    "pct_anterior": pct_anterior,
                    "delta": round(delta, 1),
                    "sugestao": _plateau_suggestion(mat, pct_atual),
                })
            elif delta < -5:  # Regressão
                plateaus.append({
                    "materia": mat,
                    "pct_atual": pct_atual,
                    "pct_anterior": pct_anterior,
                    "delta": round(delta, 1),
                    "sugestao": f"📉 Regressão em {mat}! Revise os fundamentos e resolva questões comentadas.",
                })

    return plateaus


def _plateau_suggestion(materia: str, pct: float) -> str:
    """Gera sugestão específica para sair do platô."""
    if pct < 40:
        return f"Mude a abordagem em {materia}: assista videoaulas ou use mapas mentais antes de resolver mais questões."
    elif pct < 60:
        return f"Foque em questões COMENTADAS de {materia}. Leia as explicações mesmo quando acertar."
    else:
        return f"Tente questões mais difíceis de {materia} ou simule condições de prova (tempo limitado)."


# ============================================================
# INTELIGÊNCIA 6: MICRO-METAS DINÂMICAS
# ============================================================

def _generate_micro_goals(conn, user_id: int, materias_foco: list) -> list:
    """Gera metas específicas por tópico (não apenas por matéria)."""
    micro_metas = []

    for mf in materias_foco[:3]:
        materia = mf["materia"]
        # Encontrar o tópico mais fraco dentro da matéria
        topico_fraco = conn.execute("""
            SELECT q.topico, COUNT(*) as total,
                   SUM(CASE WHEN qr.acertou = 0 THEN 1 ELSE 0 END) as erros,
                   ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND q.materia = ? AND q.topico != ''
            GROUP BY q.topico HAVING total >= 3
            ORDER BY pct ASC LIMIT 1
        """, (user_id, materia)).fetchone()

        if topico_fraco and topico_fraco["pct"] < 70:
            qtd = 10 if topico_fraco["pct"] < 40 else 7 if topico_fraco["pct"] < 60 else 5
            micro_metas.append({
                "materia": materia,
                "topico": topico_fraco["topico"],
                "meta": f"Resolver {qtd} questões de '{topico_fraco['topico']}' ({topico_fraco['pct']}% acerto)",
                "qtd_questoes": qtd,
                "pct_atual": topico_fraco["pct"],
                "prioridade": "ALTA" if topico_fraco["pct"] < 50 else "MÉDIA",
            })
        else:
            # Tópico do edital não estudado ainda
            nao_estudado = conn.execute("""
                SELECT topico FROM edital
                WHERE materia = ? AND status = 'Não Iniciado' AND arquivado = 0 AND user_id = ?
                LIMIT 1
            """, (materia, user_id)).fetchone()
            if nao_estudado:
                micro_metas.append({
                    "materia": materia,
                    "topico": nao_estudado["topico"],
                    "meta": f"Iniciar estudo de '{nao_estudado['topico']}' (novo tópico)",
                    "qtd_questoes": 5,
                    "pct_atual": 0,
                    "prioridade": "MÉDIA",
                })

    return micro_metas


# ============================================================
# INTELIGÊNCIA 7: HORÁRIO ÓTIMO
# ============================================================

def _detect_optimal_hours(conn, user_id: int) -> Optional[dict]:
    """Analisa horários de estudo para sugerir o melhor período do dia."""
    try:
        # Sessões com created_at (timestamp completo)
        rows = conn.execute("""
            SELECT created_at FROM sessoes_estudo
            WHERE user_id = ? AND created_at != '' AND created_at IS NOT NULL
            ORDER BY created_at DESC LIMIT 100
        """, (user_id,)).fetchall()

        if len(rows) < 10:
            return None

        # Extrair horas
        horas_contagem = {"manha": 0, "tarde": 0, "noite": 0, "madrugada": 0}
        for r in rows:
            try:
                ts = r["created_at"]
                # Tentar parsear diferentes formatos
                hora = None
                if "T" in ts:
                    hora = int(ts.split("T")[1][:2])
                elif " " in ts:
                    hora = int(ts.split(" ")[1][:2])

                if hora is not None:
                    if 5 <= hora < 12:
                        horas_contagem["manha"] += 1
                    elif 12 <= hora < 18:
                        horas_contagem["tarde"] += 1
                    elif 18 <= hora < 23:
                        horas_contagem["noite"] += 1
                    else:
                        horas_contagem["madrugada"] += 1
            except (ValueError, IndexError, TypeError):
                continue

        total = sum(horas_contagem.values())
        if total < 5:
            return None

        # Período dominante
        melhor_periodo = max(horas_contagem, key=horas_contagem.get)
        pct_melhor = round(horas_contagem[melhor_periodo] / total * 100, 1)

        periodos_label = {
            "manha": "☀️ Manhã (5h-12h)",
            "tarde": "🌤️ Tarde (12h-18h)",
            "noite": "🌙 Noite (18h-23h)",
            "madrugada": "🦉 Madrugada (23h-5h)",
        }

        return {
            "melhor_periodo": melhor_periodo,
            "label": periodos_label[melhor_periodo],
            "pct": pct_melhor,
            "distribuicao": {k: round(v / total * 100, 1) for k, v in horas_contagem.items()},
            "sugestao": f"Você estuda mais à {melhor_periodo} ({pct_melhor}% das sessões). Priorize esse horário para matérias difíceis.",
        }
    except Exception:
        return None


# ============================================================
# INTELIGÊNCIA 8: SPRINT MODE (< 30 DIAS)
# ============================================================

def _get_sprint_mode(conn, user_id: int, dias_prova: Optional[int],
                     edital_nome: str = "", cargo: str = "") -> Optional[dict]:
    """Quando prova < 30 dias, gera plano de revisão intensiva."""
    if dias_prova is None or dias_prova > 30:
        return None

    # Matérias mais cobradas pela banca
    banca_weights = _get_banca_weights(conn, user_id, edital_nome, cargo)

    # Tópicos com menor mastery
    query = "SELECT materia, topico, mastery_level FROM edital WHERE user_id = ? AND arquivado = 0"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " ORDER BY mastery_level ASC LIMIT 20"

    try:
        topicos_fracos = conn.execute(query, params).fetchall()
    except Exception:
        topicos_fracos = []

    # Distribuição do sprint: 70% revisão, 30% questões
    # Foco nas matérias com maior peso na banca E menor mastery
    sprint_plan = []
    for t in topicos_fracos:
        mat = t["materia"]
        peso_banca = banca_weights.get(mat, {}).get("peso_pct", 5)
        mastery = t["mastery_level"] or 0
        # Score: alto peso banca + baixo mastery = prioridade máxima
        sprint_score = peso_banca * (100 - mastery) / 100
        sprint_plan.append({
            "materia": mat,
            "topico": t["topico"],
            "mastery": round(mastery, 1),
            "peso_banca": peso_banca,
            "sprint_score": round(sprint_score, 1),
        })

    sprint_plan.sort(key=lambda x: -x["sprint_score"])

    return {
        "ativo": True,
        "dias_restantes": dias_prova,
        "estrategia": "Modo Sprint: revisão intensiva + simulados",
        "distribuicao": {"revisao_pct": 40, "questoes_pct": 40, "simulado_pct": 20},
        "focos": sprint_plan[:10],
        "dicas": [
            "Resolva pelo menos 1 simulado completo por semana",
            "Priorize questões das últimas 3 provas da banca",
            "Revise apenas tópicos já estudados — não inicie conteúdo novo",
            f"Foque {min(dias_prova, 5)} horas/dia nos {min(len(sprint_plan), 5)} tópicos mais fracos",
        ],
    }


# ============================================================
# FUNÇÕES AUXILIARES — SÍNTESE
# ============================================================

def _get_study_gaps(conn, desempenho: dict, ultima_sessao: dict) -> list:
    materias_foco = []
    hoje_date = date.today()

    for mat, stats in desempenho.items():
        if stats["total"] >= 5 and stats["pct"] < 70:
            dias_sem = _days_since_last_session(mat, ultima_sessao, hoje_date)
            prioridade = "ALTA" if stats["pct"] < 50 else "MÉDIA"
            materias_foco.append({"materia": mat, "pct_acerto": stats["pct"],
                                  "dias_sem_estudar": dias_sem, "prioridade": prioridade})

    for mat, _ultima in ultima_sessao.items():
        if mat not in [m["materia"] for m in materias_foco]:
            dias_sem = _days_since_last_session(mat, ultima_sessao, hoje_date)
            if dias_sem >= 7:
                materias_foco.append({
                    "materia": mat, "pct_acerto": desempenho.get(mat, {}).get("pct", 0),
                    "dias_sem_estudar": dias_sem, "prioridade": "MÉDIA" if dias_sem < 14 else "ALTA"
                })

    materias_foco.sort(key=lambda x: (0 if x["prioridade"] == "ALTA" else 1, x.get("pct_acerto", 100)))
    return materias_foco[:5]


def _calculate_readiness_score(pct_acerto: float, pct_edital: float, dias_semana: int,
                               ritmo: Optional[dict] = None, plateaus: list = None) -> tuple:
    """Score de prontidão enriquecido com ritmo e platôs."""
    score = (pct_acerto * WEIGHT_ACCURACY) + (pct_edital * WEIGHT_PROGRESS) + (dias_semana / 7 * 100 * WEIGHT_CONSISTENCY)

    # Bonus/penalty por ritmo
    if ritmo and ritmo.get("pct_ritmo"):
        if ritmo["pct_ritmo"] >= 100:
            score += 5  # Bonus por ritmo adequado
        elif ritmo["pct_ritmo"] < 50:
            score -= 10  # Penalty por ritmo crítico

    # Penalty por platôs
    if plateaus:
        score -= len(plateaus) * 3

    score = min(100, max(0, round(score, 1)))
    if score >= 80:
        nivel = "Avançado"
    elif score >= 60:
        nivel = "Intermediário"
    elif score >= 40:
        nivel = "Regular"
    elif score >= 20:
        nivel = "Iniciante"
    else:
        nivel = "Começando"
    return score, nivel


def _generate_recommendations(materias_foco: list, pending: dict, streak: int,
                              horas_hoje: float, meta_horas: float, dias_prova,
                              error_patterns: list = None, micro_metas: list = None,
                              sprint_mode: dict = None, plateaus: list = None) -> list:
    """Gera recomendações inteligentes com base em todos os sinais."""
    recomendacoes = []

    # Sprint mode override
    if sprint_mode and sprint_mode.get("ativo"):
        recomendacoes.append({
            "tipo": "alerta",
            "msg": f"🏃 MODO SPRINT ATIVO — Prova em {sprint_mode['dias_restantes']} dias! Revisão intensiva + simulados.",
            "destaque": True,
        })

    # Revisões SRS (sempre prioritárias)
    if pending["flashcards"] > 0:
        n = pending["flashcards"]
        recomendacoes.append({"tipo": "revisar", "msg": f"Revisar {n} flashcard{'s' if n > 1 else ''} pendente{'s' if n > 1 else ''}", "acao": "/flashcards"})
    if pending["topicos"] > 0:
        n = pending["topicos"]
        recomendacoes.append({"tipo": "revisar", "msg": f"Revisar {n} tópico{'s' if n > 1 else ''} do edital com revisão pendente", "acao": "/edital"})

    # Micro-metas (mais específicas que matérias genéricas)
    if micro_metas:
        for mm in micro_metas[:2]:
            recomendacoes.append({
                "tipo": "questoes",
                "msg": mm["meta"],
                "materia": mm["materia"],
                "topico": mm["topico"],
                "qtd": mm["qtd_questoes"],
            })
    else:
        # Fallback: matérias foco genéricas
        for mf in materias_foco[:2]:
            qtd = 10 if mf["pct_acerto"] < 50 else 5
            recomendacoes.append({"tipo": "questoes", "msg": f"Resolver {qtd} questões de {mf['materia']} ({mf['pct_acerto']}% acerto)", "materia": mf["materia"], "qtd": qtd})

    # Padrão de erros (cirúrgico)
    if error_patterns:
        for ep in error_patterns[:1]:
            recomendacoes.append({
                "tipo": "questoes",
                "msg": f"🎯 Revisar '{ep['topico']}' em {ep['materia']} — {ep['pct_erro']}% de erro recente",
                "materia": ep["materia"],
                "topico": ep["topico"],
            })

    # Matéria esquecida
    for mf in materias_foco:
        if mf.get("dias_sem_estudar", 0) >= 7:
            recomendacoes.append({"tipo": "estudar", "msg": f"Estudar {mf['materia']} ({mf['dias_sem_estudar']} dias sem sessão)", "materia": mf["materia"]})
            break

    # Platô detectado
    if plateaus:
        for p in plateaus[:1]:
            recomendacoes.append({"tipo": "alerta", "msg": p["sugestao"]})

    # Countdown com urgência
    if dias_prova is not None and dias_prova <= 30:
        if not sprint_mode:  # Evitar duplicar com sprint mode
            recomendacoes.append({"tipo": "alerta", "msg": f"🚨 Prova em {dias_prova} dias! Foco total!"})
    elif dias_prova is not None and dias_prova <= 60:
        recomendacoes.append({"tipo": "alerta", "msg": f"⚠️ Prova em {dias_prova} dias! Aumente o ritmo."})
    elif dias_prova is not None and dias_prova <= 120:
        recomendacoes.append({"tipo": "alerta", "msg": f"📅 Prova em {dias_prova} dias. Mantenha a consistência."})

    # Streak em risco
    if streak == 0 and horas_hoje == 0:
        recomendacoes.append({"tipo": "alerta", "msg": "⚠️ Streak em risco! Estude hoje para manter a sequência."})

    # Meta diária
    if horas_hoje < meta_horas * 0.5:
        recomendacoes.append({"tipo": "alerta", "msg": f"📊 Meta de {meta_horas}h ainda não atingida ({horas_hoje:.1f}h cumpridas)"})

    return recomendacoes


def _dias_ate_prova(conn, user_id: int, edital_nome: str = "", cargo: str = ""):
    """Retorna dias até a próxima prova FUTURA (ignora provas já passadas)."""
    try:
        query = """SELECT data_prova_objetiva FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?"""
        params = [user_id]
        if edital_nome:
            query += " AND edital_nome = ?"
            params.append(edital_nome)
        if cargo:
            query += " AND cargo = ?"
            params.append(cargo)
        rows = conn.execute(query, params).fetchall()

        hoje = date.today()
        menor_dias = None

        for row in rows:
            data_str = row[0]
            parts = re.match(r'(\d+)[/\-](\d+)[/\-](\d+)', data_str)
            if not parts:
                continue
            if len(parts.group(3)) == 4:
                # dd/mm/yyyy
                d = date(int(parts.group(3)), int(parts.group(2)), int(parts.group(1)))
            else:
                # yyyy-mm-dd
                d = date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
            dias = (d - hoje).days
            if dias > 0 and (menor_dias is None or dias < menor_dias):
                menor_dias = dias

        return menor_dias
    except Exception as e:
        log.warning(f"Could not calculate days until exam: {e}")
    return None


def _get_priority_activities(conn, desempenho: dict, ultima_sessao: dict,
                             user_id: int, edital_nome: str = "", cargo: str = "") -> list:
    materias_priority = []
    hoje_date = date.today()

    # Pre-fetch avg mastery per materia for scoring
    mastery_by_materia = {}
    try:
        mastery_rows = conn.execute("""
            SELECT materia, AVG(mastery_level) as avg_mastery
            FROM edital WHERE user_id = ? AND arquivado = 0 AND mastery_level > 0
            GROUP BY materia
        """, (user_id,)).fetchall()
        for mr in mastery_rows:
            mastery_by_materia[mr["materia"]] = mr["avg_mastery"] or 0
    except Exception:
        pass  # mastery columns may not exist yet

    for mat, stats in desempenho.items():
        if stats["total"] >= 3:
            dias_sem = _days_since_last_session(mat, ultima_sessao, hoje_date)
            priority_score = (100 - stats["pct"]) + dias_sem * 2
            # Mastery factor: low mastery increases priority
            avg_mastery = mastery_by_materia.get(mat, 0)
            if avg_mastery > 0:
                priority_score += (100 - avg_mastery) * 0.3
            materias_priority.append({"materia": mat, "pct": stats["pct"], "dias_sem": dias_sem, "score": priority_score})

    materias_edital_query = "SELECT DISTINCT materia FROM edital WHERE status != 'Concluído' AND user_id = ?"
    params_edital = [user_id]
    if edital_nome:
        materias_edital_query += " AND edital_nome = ?"
        params_edital.append(edital_nome)
    if cargo:
        materias_edital_query += " AND cargo = ?"
        params_edital.append(cargo)
    materias_edital = [r[0] for r in conn.execute(materias_edital_query, params_edital).fetchall()]

    for mat in materias_edital:
        if mat not in desempenho:
            dias_sem = _days_since_last_session(mat, ultima_sessao, hoje_date)
            materias_priority.append({"materia": mat, "pct": 0, "dias_sem": dias_sem, "score": 100 + dias_sem * 2})

    materias_priority.sort(key=lambda x: -x["score"])
    return materias_priority[:3]


def _distribute_time(conn, top_materias: list, tempo_restante: int, ordem: int,
                     user_id: int, edital_nome: str = "", cargo: str = "") -> tuple:
    atividades = []
    if not top_materias or tempo_restante <= 0:
        return atividades, ordem

    total_score = sum(m["score"] for m in top_materias) or 1
    for mat_info in top_materias:
        if tempo_restante <= 0:
            break
        proporcao = mat_info["score"] / total_score
        tempo_materia = int(tempo_restante * proporcao)
        if tempo_materia < 15:
            tempo_materia = min(15, tempo_restante)

        tempo_estudo = int(tempo_materia * 0.6)
        tempo_questoes = tempo_materia - tempo_estudo

        topicos_query = "SELECT topico FROM edital WHERE materia = ? AND status != 'Concluído' AND user_id = ?"
        topicos_params = [mat_info["materia"], user_id]
        if edital_nome:
            topicos_query += " AND edital_nome = ?"
            topicos_params.append(edital_nome)
        if cargo:
            topicos_query += " AND cargo = ?"
            topicos_params.append(cargo)
        topicos_query += f" LIMIT 3"
        topicos = [r[0] for r in conn.execute(topicos_query, topicos_params).fetchall()]

        if tempo_estudo >= 10:
            atividades.append({"ordem": ordem, "tipo": "estudo", "materia": mat_info["materia"],
                               "topicos": topicos if topicos else ["Revisão geral"], "tempo_min": tempo_estudo})
            ordem += 1
        if tempo_questoes >= 10:
            qtd_questoes = max(5, tempo_questoes // 2)
            atividades.append({"ordem": ordem, "tipo": "questoes", "materia": mat_info["materia"],
                               "qtd": qtd_questoes, "tempo_min": tempo_questoes})
            ordem += 1
        tempo_restante -= tempo_materia

    return atividades, ordem


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/api/treinador", summary="Treinador Inteligente")
def treinador_inteligente(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Treinador com 8 camadas de inteligência: erros, ritmo, FSRS, banca, platô, micro-metas, horário, sprint."""
    desempenho = _get_performance_by_subject(conn, user_id)
    ultima_sessao = _get_last_session_by_subject(conn, user_id)
    pending = _get_pending_reviews(conn, user_id)

    query_edital = "SELECT COUNT(*) FROM edital WHERE user_id = ?"
    query_done = "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?"
    params_edital = [user_id]
    if edital_nome:
        query_edital += " AND edital_nome = ?"
        query_done += " AND edital_nome = ?"
        params_edital.append(edital_nome)
    if cargo:
        query_edital += " AND cargo = ?"
        query_done += " AND cargo = ?"
        params_edital.append(cargo)
    edital_total = conn.execute(query_edital, params_edital).fetchone()[0]
    edital_concluido = conn.execute(query_done, params_edital).fetchone()[0]

    inicio_semana = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    dias_semana = conn.execute("""
        SELECT COUNT(DISTINCT data) FROM streaks
        WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0) AND user_id = ?
    """, (inicio_semana, user_id)).fetchone()[0]

    metas = conn.execute("SELECT meta_horas, meta_questoes FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    meta_horas = metas[0] if metas else 3.0
    meta_questoes = metas[1] if metas else 30
    hoje_streak = conn.execute("SELECT horas_estudadas, questoes_resolvidas FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    horas_hoje = hoje_streak[0] if hoje_streak else 0
    questoes_hoje = hoje_streak[1] if hoje_streak else 0

    streak_info = calculate_streak(conn, user_id)
    streak = streak_info["streak_atual"]
    dias_prova = _dias_ate_prova(conn, user_id, edital_nome, cargo)

    q_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    q_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    pct_acerto_global = (q_acertos / q_total * 100) if q_total > 0 else 0
    pct_edital = (edital_concluido / edital_total * 100) if edital_total > 0 else 0

    # ===== 8 CAMADAS DE INTELIGÊNCIA =====
    # 1. Padrão de erros
    error_patterns = _analyze_error_patterns(conn, user_id)

    # 2. Ritmo adaptativo
    ritmo = _calculate_adaptive_pace(conn, user_id, dias_prova, edital_nome, cargo)

    # 3. Curva de esquecimento (FSRS)
    forgetting_risk = _get_forgetting_risk(conn, user_id)

    # 4. Peso da banca
    banca_weights = _get_banca_weights(conn, user_id, edital_nome, cargo)

    # 5. Detecção de platô
    plateaus = _detect_plateaus(conn, user_id)

    # 6. Micro-metas dinâmicas
    materias_foco = _get_study_gaps(conn, desempenho, ultima_sessao)
    micro_metas = _generate_micro_goals(conn, user_id, materias_foco)

    # 7. Horário ótimo
    horario_otimo = _detect_optimal_hours(conn, user_id)

    # 8. Sprint mode
    sprint_mode = _get_sprint_mode(conn, user_id, dias_prova, edital_nome, cargo)

    # Score enriquecido
    score, nivel = _calculate_readiness_score(pct_acerto_global, pct_edital, dias_semana, ritmo, plateaus)

    # Recomendações com todas as inteligências
    recomendacoes = _generate_recommendations(
        materias_foco, pending, streak, horas_hoje, meta_horas, dias_prova,
        error_patterns=error_patterns,
        micro_metas=micro_metas,
        sprint_mode=sprint_mode,
        plateaus=plateaus,
    )

    log.info(f"Treinador: score={score} nivel={nivel} recs={len(recomendacoes)} erros={len(error_patterns)} platos={len(plateaus)}")
    return {
        "score_prontidao": score,
        "nivel": nivel,
        "recomendacoes": recomendacoes,
        "materias_foco": materias_foco,
        "revisoes_pendentes": {"flashcards": pending["flashcards"], "topicos": pending["topicos"]},
        "meta_hoje": {"horas": meta_horas, "questoes": int(meta_questoes),
                      "cumprido_horas": round(horas_hoje, 1), "cumprido_questoes": int(questoes_hoje)},
        # Novas inteligências
        "inteligencia": {
            "error_patterns": error_patterns[:3],
            "ritmo_adaptativo": ritmo,
            "forgetting_risk": forgetting_risk[:5],
            "banca_weights": dict(list(banca_weights.items())[:5]) if banca_weights else None,
            "plateaus": plateaus,
            "micro_metas": micro_metas,
            "horario_otimo": horario_otimo,
            "sprint_mode": sprint_mode,
        },
        "dias_prova": dias_prova,
    }


@router.get("/api/trilha-diaria", summary="Trilha de Estudo Diária")
def trilha_diaria(edital_nome: str = "", cargo: str = "", horas_disponiveis: float = Query(default=3.0), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    tempo_total_min = int(horas_disponiveis * 60)
    tempo_restante = tempo_total_min
    atividades = []
    ordem = 1

    pending = _get_pending_reviews(conn, user_id)

    if pending["flashcards"] > 0 and tempo_restante > 0:
        tempo_flash = min(max(5, pending["flashcards"] * 2), 20)
        tempo_flash = min(tempo_flash, tempo_restante)
        atividades.append({"ordem": ordem, "tipo": "revisao",
                           "descricao": f"Revisar {pending['flashcards']} flashcard{'s' if pending['flashcards'] > 1 else ''} pendente{'s' if pending['flashcards'] > 1 else ''}",
                           "tempo_min": tempo_flash})
        tempo_restante -= tempo_flash
        ordem += 1

    if pending["topicos"] > 0 and tempo_restante > 0:
        tempo_top = min(max(5, pending["topicos"] * 5), 30)
        tempo_top = min(tempo_top, tempo_restante)
        atividades.append({"ordem": ordem, "tipo": "revisao",
                           "descricao": f"Revisar {pending['topicos']} tópico{'s' if pending['topicos'] > 1 else ''} com baixa retenção",
                           "tempo_min": tempo_top})
        tempo_restante -= tempo_top
        ordem += 1

    desempenho = _get_performance_by_subject(conn, user_id)
    ultima_sessao = _get_last_session_by_subject(conn, user_id)
    top_materias = _get_priority_activities(conn, desempenho, ultima_sessao, user_id, edital_nome, cargo)
    new_atividades, ordem = _distribute_time(conn, top_materias, tempo_restante, ordem, user_id, edital_nome, cargo)
    atividades.extend(new_atividades)

    tempo_total_real = sum(a["tempo_min"] for a in atividades)
    foco_principal = top_materias[0]["materia"] if top_materias else "Revisão"
    motivo = ""
    if top_materias:
        m = top_materias[0]
        motivos = []
        if m["pct"] > 0:
            motivos.append(f"Menor % de acerto ({m['pct']}%)")
        if m["dias_sem"] > 0:
            motivos.append(f"{m['dias_sem']} dias sem estudar")
        dias_prova_val = _dias_ate_prova(conn, user_id, edital_nome, cargo) if edital_nome else None
        if dias_prova_val is not None:
            motivos.append(f"prova em {dias_prova_val} dias")
        motivo = " + ".join(motivos) if motivos else "Matéria prioritária"

    log.info(f"Trilha diária gerada: {len(atividades)} atividades, {tempo_total_real}min, foco={foco_principal}")
    return {"data": today_str(), "horas_disponiveis": horas_disponiveis, "atividades": atividades,
            "tempo_total_min": tempo_total_real, "foco_principal": foco_principal, "motivo": motivo}


# ============================================================
# CALENDÁRIO SEMANAL (geração inteligente)
# ============================================================

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _get_uncompleted_topics(conn, materia: str, user_id: int, edital_nome: str = "", cargo: str = "", limit: int = 3) -> list:
    query = "SELECT topico FROM edital WHERE materia = ? AND status != 'Concluído' AND user_id = ?"
    params = [materia, user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += f" LIMIT {limit}"
    return [r[0] for r in conn.execute(query, params).fetchall()]


def _gerar_planejador_interno(conn, user_id: int, horas_dia: float = 3.0):
    """Gera planejador internamente (sem HTTP). Cascata: gera ciclo se necessário."""
    from routers.ciclo import _gerar_ciclo_automatico

    ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()
    if not ciclo:
        _gerar_ciclo_automatico(conn, user_id, horas_dia)
        ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()
    if not ciclo:
        return

    materias_scored = []
    for c in ciclo:
        mat = c["materia"]
        desemp = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id WHERE q.materia = ? AND qr.user_id = ?
        """, (mat, user_id)).fetchone()
        total_q = desemp[0] or 0
        pct_acerto = (desemp[1] / total_q * 100) if total_q > 0 else 0
        horas_estudadas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ? AND user_id = ?", (mat, user_id)).fetchone()[0]
        pendentes = conn.execute("SELECT COUNT(*) FROM edital WHERE materia = ? AND status != 'Concluído' AND arquivado = 0 AND user_id = ?", (mat, user_id)).fetchone()[0]
        ultima = conn.execute("SELECT MAX(data) FROM sessoes_estudo WHERE materia = ? AND user_id = ?", (mat, user_id)).fetchone()[0]
        try:
            dias_sem = (date.today() - date.fromisoformat(ultima)).days if ultima else 999
        except (ValueError, TypeError):
            dias_sem = 30

        score = (100 - pct_acerto) * 0.35 + min(pendentes * 2, 25) + c["horas_alvo"] * 5
        if horas_estudadas < c["horas_alvo"] * 2:
            score += 10
        if dias_sem >= 999:
            score += 15
        elif dias_sem >= 7:
            score += 8
        if total_q == 0:
            score += 8
        materias_scored.append({"materia": mat, "score": score, "horas_alvo": c["horas_alvo"], "pct_acerto": pct_acerto})

    materias_scored.sort(key=lambda x: -x["score"])
    total_mats = len(materias_scored)
    for i, m in enumerate(materias_scored):
        pos = i / max(total_mats, 1)
        m["freq"] = 3 if pos < 0.3 else 2 if pos < 0.65 else 1

    SLOTS_POR_DIA = [3, 2, 3, 2, 3, 2]
    dias = [[] for _ in range(7)]
    pool = []
    for m in materias_scored:
        pool.extend([m] * m["freq"])

    last_day_materias = set()
    pool_idx = 0
    for dia in range(6):
        target = SLOTS_POR_DIA[dia]
        used_today = set()
        attempts = 0
        search_idx = pool_idx
        while len(dias[dia]) < target and attempts < len(pool) * 3:
            if not pool:
                break
            candidate = pool[search_idx % len(pool)]
            if candidate["materia"] not in last_day_materias and candidate["materia"] not in used_today:
                horas_slot = round(horas_dia / target, 1)
                if candidate["score"] > 50:
                    horas_slot = round(horas_slot * 1.2, 1)
                horas_slot = min(2.0, max(0.5, horas_slot))
                dias[dia].append({"materia": candidate["materia"], "horas": horas_slot})
                used_today.add(candidate["materia"])
                pool_idx = (search_idx + 1) % len(pool)
            search_idx += 1
            attempts += 1
        if len(dias[dia]) < target:
            for m in materias_scored:
                if m["materia"] not in used_today:
                    dias[dia].append({"materia": m["materia"], "horas": round(horas_dia / target, 1)})
                    used_today.add(m["materia"])
                    if len(dias[dia]) >= target:
                        break
        last_day_materias = used_today

    for m in materias_scored[:2]:
        dias[6].append({"materia": m["materia"], "horas": 0.5})

    conn.execute("DELETE FROM planejador_semanal WHERE user_id = ?", (user_id,))
    for dia_idx, slots in enumerate(dias):
        for slot in slots:
            conn.execute("INSERT INTO planejador_semanal (dia_semana, materia, horas, user_id) VALUES (?, ?, ?, ?)",
                         (dia_idx, slot["materia"], slot["horas"], user_id))
    conn.commit()


@router.get("/api/calendario-semanal", summary="Calendário Semanal")
def calendario_semanal(edital_nome: str = "", cargo: str = "", horas_dia: float = Query(default=3.0), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera calendário semanal de estudos."""
    tempo_dia_min = int(horas_dia * 60)

    planejador = conn.execute("SELECT * FROM planejador_semanal WHERE user_id = ? ORDER BY dia_semana, id", (user_id,)).fetchall()
    planejador_gerado = False
    if not planejador:
        _gerar_planejador_interno(conn, user_id, horas_dia)
        planejador = conn.execute("SELECT * FROM planejador_semanal WHERE user_id = ? ORDER BY dia_semana, id", (user_id,)).fetchall()
        planejador_gerado = True

    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())

    if not planejador:
        return {
            "semana_inicio": inicio_semana.isoformat(),
            "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
            "horas_dia": horas_dia, "planejador_gerado": False,
            "dias": [{"dia_semana": i, "nome": NOMES_DIAS[i],
                      "data": (inicio_semana + timedelta(days=i)).isoformat(),
                      "atividades": [{"tipo": "revisao", "descricao": "Adicione matérias ao edital para gerar o calendário", "tempo_min": 0, "materia": None}],
                      "tempo_total_min": 0, "materias": []} for i in range(7)],
            "resumo": {"total_materias": 0, "horas_semana": 0, "distribuicao": []}
        }

    plan_por_dia = {i: [] for i in range(7)}
    for p in planejador:
        plan_por_dia[p["dia_semana"]].append({"materia": p["materia"], "horas": p["horas"]})

    desempenho = _get_performance_by_subject(conn, user_id)
    pending = _get_pending_reviews(conn, user_id)

    dias = []
    distribuicao_map = {}

    for day_idx in range(7):
        data_dia = inicio_semana + timedelta(days=day_idx)
        atividades = []
        tempo_restante = tempo_dia_min
        materias_do_dia = []
        is_domingo = day_idx == 6

        if pending["flashcards"] > 0:
            tempo_flash = min(10, tempo_restante)
            atividades.append({"tipo": "revisao", "descricao": f"Revisar {pending['flashcards']} flashcards pendentes", "tempo_min": tempo_flash, "materia": None})
            tempo_restante -= tempo_flash

        day_plan = plan_por_dia.get(day_idx, [])

        if is_domingo and not day_plan:
            if pending["topicos"] > 0:
                tempo_top = min(15, tempo_restante)
                atividades.append({"tipo": "revisao", "descricao": f"Revisar {pending['topicos']} tópicos com baixa retenção", "tempo_min": tempo_top, "materia": None})
                tempo_restante -= tempo_top
            if tempo_restante >= 10:
                atividades.append({"tipo": "revisao", "descricao": "Revisão geral da semana", "tempo_min": min(15, tempo_restante), "materia": None})
        elif day_plan:
            tempo_revisao_final = 10
            tempo_para_materias = tempo_restante - tempo_revisao_final

            for slot in day_plan:
                if tempo_para_materias <= 0:
                    break
                materia_nome = slot["materia"]
                materias_do_dia.append(materia_nome)
                if materia_nome not in distribuicao_map:
                    distribuicao_map[materia_nome] = {"dias": [], "tempo_total": 0}
                distribuicao_map[materia_nome]["dias"].append(day_idx)

                total_horas_dia = sum(s["horas"] for s in day_plan) or 1
                proporcao = slot["horas"] / total_horas_dia
                tempo_materia = int(tempo_para_materias * proporcao)

                topicos = _get_uncompleted_topics(conn, materia_nome, user_id, edital_nome, cargo, limit=3)
                if not topicos:
                    topicos = ["Revisão geral"]

                perf = desempenho.get(materia_nome, {})
                pct = perf.get("pct", 0)
                if pct < 50 and perf.get("total", 0) > 0:
                    tempo_estudo = int(tempo_materia * 0.45)
                    tempo_questoes = int(tempo_materia * 0.45)
                elif pct > 80:
                    tempo_estudo = int(tempo_materia * 0.7)
                    tempo_questoes = int(tempo_materia * 0.2)
                else:
                    tempo_estudo = int(tempo_materia * 0.6)
                    tempo_questoes = int(tempo_materia * 0.3)

                if tempo_estudo >= 15:
                    atividades.append({"tipo": "estudo", "materia": materia_nome, "topicos": topicos, "tempo_min": tempo_estudo})
                if tempo_questoes >= 10:
                    qtd_questoes = max(5, tempo_questoes // 2)
                    atividades.append({"tipo": "questoes", "materia": materia_nome, "qtd": qtd_questoes, "tempo_min": tempo_questoes})

                distribuicao_map[materia_nome]["tempo_total"] += tempo_estudo + tempo_questoes
                tempo_para_materias -= (tempo_estudo + tempo_questoes)

            if tempo_revisao_final > 0:
                atividades.append({"tipo": "revisao", "descricao": "Resumo do dia (Técnica Feynman)", "tempo_min": tempo_revisao_final, "materia": None})

        tempo_total_dia = sum(a["tempo_min"] for a in atividades)
        dias.append({"dia_semana": day_idx, "nome": NOMES_DIAS[day_idx], "data": data_dia.isoformat(),
                     "atividades": atividades, "tempo_total_min": tempo_total_dia, "materias": materias_do_dia})

    distribuicao = []
    for materia, info in distribuicao_map.items():
        tempo_total_materia = sum(a["tempo_min"] for d in dias for a in d["atividades"] if a.get("materia") == materia)
        distribuicao.append({"materia": materia, "dias": sorted(set(info["dias"])), "horas_semana": round(tempo_total_materia / 60, 1)})
    distribuicao.sort(key=lambda x: -x["horas_semana"])

    horas_semana_total = round(sum(d["tempo_total_min"] for d in dias) / 60, 1)
    total_materias = len(set(m for d in dias for m in d["materias"]))

    log.info(f"Calendário semanal gerado: {total_materias} matérias, {horas_semana_total}h/semana")
    return {
        "semana_inicio": inicio_semana.isoformat(),
        "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
        "horas_dia": horas_dia, "planejador_gerado": planejador_gerado,
        "dias": dias,
        "resumo": {"total_materias": total_materias, "horas_semana": horas_semana_total, "distribuicao": distribuicao}
    }


@router.get("/api/treinador/sugestao-rapida")
def sugestao_rapida(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a melhor matéria para estudar agora (para CTA 'Iniciar Sessão')."""
    # Priority: matéria com menor acerto + mais tempo sem estudar
    fraca = conn.execute("""
        SELECT q.materia, COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? GROUP BY q.materia HAVING total >= 3
        ORDER BY pct ASC LIMIT 1
    """, (user_id,)).fetchone()

    if fraca:
        return {"materia": fraca[0], "motivo": f"Menor acerto ({fraca[2]}%)", "tempo_min": 25}

    # Fallback: matéria com menos horas estudadas
    menos_estudada = conn.execute("""
        SELECT materia FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?
        GROUP BY materia ORDER BY SUM(horas_estudadas) ASC LIMIT 1
    """, (user_id,)).fetchone()

    if menos_estudada:
        return {"materia": menos_estudada[0], "motivo": "Menos estudada", "tempo_min": 25}

    # Final fallback
    return {"materia": "Revisão Geral", "motivo": "Estudo geral", "tempo_min": 25}

"""Funções auxiliares de análise do Treinador Inteligente.

Contém as 8 camadas de inteligência e helpers compartilhados entre os endpoints.
"""
import math
import re
from datetime import date, timedelta
from typing import Optional

from constants import WEIGHT_ACCURACY, WEIGHT_CONSISTENCY, WEIGHT_PROGRESS
from logger import log
from utils import today_str


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
                "descricao": fc["pergunta"],
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
                "descricao": f"{t['materia']}: {t['topico']}",
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

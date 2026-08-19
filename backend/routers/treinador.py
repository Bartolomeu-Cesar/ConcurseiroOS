import re
from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, Query

from constants import WEIGHT_ACCURACY, WEIGHT_CONSISTENCY, WEIGHT_PROGRESS
from database import get_db_session
from logger import log
from utils import calculate_streak, today_str

router = APIRouter(prefix="", tags=["Treinador Inteligente"])


# ============================================================
# FUNÇÕES AUXILIARES EXTRAÍDAS
# ============================================================

def _get_performance_by_subject(conn) -> dict:
    """Retorna desempenho por matéria (% acerto, total questões)."""
    rows = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
    """).fetchall()
    return {r[0]: {"total": r[1], "acertos": r[2] or 0, "pct": round((r[2] or 0) / r[1] * 100, 1) if r[1] > 0 else 0} for r in rows}


def _get_last_session_by_subject(conn) -> dict:
    """Retorna a data da última sessão de estudo por matéria."""
    rows = conn.execute("""
        SELECT materia, MAX(data) as ultima FROM sessoes_estudo GROUP BY materia
    """).fetchall()
    return {r[0]: r[1] for r in rows}


def _get_pending_reviews(conn) -> dict:
    """Retorna contagem de revisões pendentes (flashcards e tópicos)."""
    flashcards = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)
    ).fetchone()[0]
    topicos = conn.execute("""
        SELECT COUNT(*) FROM edital
        WHERE proxima_revisao != '' AND proxima_revisao <= ?
    """, (today_str(),)).fetchone()[0]
    return {"flashcards": flashcards, "topicos": topicos}


def _get_study_gaps(conn, desempenho: dict, ultima_sessao: dict) -> list:
    """Retorna matérias prioritárias baseado em desempenho e dias sem estudar."""
    materias_foco = []
    hoje_date = date.today()

    for mat, stats in desempenho.items():
        if stats["total"] >= 5 and stats["pct"] < 70:
            dias_sem = _days_since_last_session(mat, ultima_sessao, hoje_date)
            prioridade = "ALTA" if stats["pct"] < 50 else "MÉDIA"
            materias_foco.append({
                "materia": mat,
                "pct_acerto": stats["pct"],
                "dias_sem_estudar": dias_sem,
                "prioridade": prioridade
            })

    # Adicionar matérias com muitos dias sem estudar
    for mat, _ultima in ultima_sessao.items():
        if mat not in [m["materia"] for m in materias_foco]:
            dias_sem = _days_since_last_session(mat, ultima_sessao, hoje_date)
            if dias_sem >= 7:
                materias_foco.append({
                    "materia": mat,
                    "pct_acerto": desempenho.get(mat, {}).get("pct", 0),
                    "dias_sem_estudar": dias_sem,
                    "prioridade": "MÉDIA" if dias_sem < 14 else "ALTA"
                })

    materias_foco.sort(key=lambda x: (0 if x["prioridade"] == "ALTA" else 1, x.get("pct_acerto", 100)))
    return materias_foco[:5]


def _days_since_last_session(materia: str, ultima_sessao: dict, hoje: date) -> int:
    """Calcula dias desde a última sessão de uma matéria."""
    if materia in ultima_sessao and ultima_sessao[materia]:
        try:
            ultima = date.fromisoformat(ultima_sessao[materia])
            return (hoje - ultima).days
        except (ValueError, TypeError):
            pass
    return 0


def _calculate_readiness_score(pct_acerto: float, pct_edital: float, dias_semana: int) -> tuple:
    """Calcula score de prontidão e nível."""
    score = (pct_acerto * WEIGHT_ACCURACY) + (pct_edital * WEIGHT_PROGRESS) + (dias_semana / 7 * 100 * WEIGHT_CONSISTENCY)
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
                              horas_hoje: float, meta_horas: float, dias_prova) -> list:
    """Gera lista de recomendações baseada no contexto do estudante."""
    recomendacoes = []

    # Revisões pendentes
    if pending["flashcards"] > 0:
        n = pending["flashcards"]
        recomendacoes.append({
            "tipo": "revisar",
            "msg": f"Revisar {n} flashcard{'s' if n > 1 else ''} pendente{'s' if n > 1 else ''}",
            "acao": "/flashcards"
        })

    if pending["topicos"] > 0:
        n = pending["topicos"]
        recomendacoes.append({
            "tipo": "revisar",
            "msg": f"Revisar {n} tópico{'s' if n > 1 else ''} do edital com revisão pendente",
            "acao": "/edital"
        })

    # Questões das matérias fracas
    for mf in materias_foco[:2]:
        qtd = 10 if mf["pct_acerto"] < 50 else 5
        recomendacoes.append({
            "tipo": "questoes",
            "msg": f"Resolver {qtd} questões de {mf['materia']} ({mf['pct_acerto']}% acerto)",
            "materia": mf["materia"],
            "qtd": qtd
        })

    # Matérias com muitos dias sem estudar
    for mf in materias_foco:
        if mf.get("dias_sem_estudar", 0) >= 7:
            recomendacoes.append({
                "tipo": "estudar",
                "msg": f"Estudar {mf['materia']} ({mf['dias_sem_estudar']} dias sem sessão)",
                "materia": mf["materia"]
            })
            break

    # Alertas
    if dias_prova is not None and dias_prova <= 60:
        recomendacoes.append({
            "tipo": "alerta",
            "msg": f"🚨 Prova em {dias_prova} dias! Aumente o ritmo."
        })

    if streak == 0 and horas_hoje == 0:
        recomendacoes.append({
            "tipo": "alerta",
            "msg": "⚠️ Streak em risco! Estude hoje para manter a sequência."
        })

    if horas_hoje < meta_horas * 0.5:
        recomendacoes.append({
            "tipo": "alerta",
            "msg": f"📊 Meta de {meta_horas}h ainda não atingida ({horas_hoje:.1f}h cumpridas)"
        })

    return recomendacoes


def _dias_ate_prova(conn, edital_nome: str = "", cargo: str = ""):
    """Retorna dias até a próxima prova."""
    try:
        query = """
            SELECT data_prova_objetiva FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital'
        """
        params = []
        if edital_nome:
            query += " AND edital_nome = ?"
            params.append(edital_nome)
        if cargo:
            query += " AND cargo = ?"
            params.append(cargo)
        query += " ORDER BY data_prova_objetiva LIMIT 1"
        prova = conn.execute(query, params).fetchone()
        if prova and prova[0]:
            parts = re.match(r'(\d+)[/\-](\d+)[/\-](\d+)', prova[0])
            if parts:
                if len(parts.group(3)) == 4:
                    d = date(int(parts.group(3)), int(parts.group(2)), int(parts.group(1)))
                else:
                    d = date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
                return max(0, (d - date.today()).days)
    except Exception as e:
        log.warning(f"Could not calculate days until exam: {e}")
    return None


def _get_priority_activities(conn, desempenho: dict, ultima_sessao: dict,
                             edital_nome: str = "", cargo: str = "") -> list:
    """Retorna matérias priorizadas para trilha diária."""
    materias_priority = []
    hoje_date = date.today()

    for mat, stats in desempenho.items():
        if stats["total"] >= 3:
            dias_sem = _days_since_last_session(mat, ultima_sessao, hoje_date)
            # Score de prioridade: menor acerto + mais dias = mais prioritário
            priority_score = (100 - stats["pct"]) + dias_sem * 2
            materias_priority.append({
                "materia": mat,
                "pct": stats["pct"],
                "dias_sem": dias_sem,
                "score": priority_score
            })

    # Adicionar matérias sem questões respondidas mas com tópicos no edital
    materias_edital_query = "SELECT DISTINCT materia FROM edital WHERE status != 'Concluído'"
    params_edital = []
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
            materias_priority.append({
                "materia": mat,
                "pct": 0,
                "dias_sem": dias_sem,
                "score": 100 + dias_sem * 2
            })

    materias_priority.sort(key=lambda x: -x["score"])
    return materias_priority[:3]


def _distribute_time(conn, top_materias: list, tempo_restante: int, ordem: int,
                     edital_nome: str = "", cargo: str = "") -> tuple:
    """Distribui tempo entre matérias prioritárias. Retorna (atividades, nova_ordem)."""
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

        # Dividir entre estudo e questões (60/40)
        tempo_estudo = int(tempo_materia * 0.6)
        tempo_questoes = tempo_materia - tempo_estudo

        # Buscar tópicos não concluídos dessa matéria
        topicos_query = "SELECT topico FROM edital WHERE materia = ? AND status != 'Concluído'"
        topicos_params = [mat_info["materia"]]
        if edital_nome:
            topicos_query += " AND edital_nome = ?"
            topicos_params.append(edital_nome)
        if cargo:
            topicos_query += " AND cargo = ?"
            topicos_params.append(cargo)
        topicos_query += " LIMIT 3"
        topicos = [r[0] for r in conn.execute(topicos_query, topicos_params).fetchall()]

        if tempo_estudo >= 10:
            atividades.append({
                "ordem": ordem,
                "tipo": "estudo",
                "materia": mat_info["materia"],
                "topicos": topicos if topicos else ["Revisão geral"],
                "tempo_min": tempo_estudo
            })
            ordem += 1

        if tempo_questoes >= 10:
            qtd_questoes = max(5, tempo_questoes // 2)  # ~2min por questão
            atividades.append({
                "ordem": ordem,
                "tipo": "questoes",
                "materia": mat_info["materia"],
                "qtd": qtd_questoes,
                "tempo_min": tempo_questoes
            })
            ordem += 1

        tempo_restante -= tempo_materia

    return atividades, ordem


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/api/treinador", summary="Treinador Inteligente", description="Retorna recomendações de estudo personalizadas baseadas em desempenho e progresso")
def treinador_inteligente(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Treinador inteligente: recomendações baseadas em desempenho, revisões pendentes e metas"""
    # 1. Desempenho por matéria
    desempenho = _get_performance_by_subject(conn)

    # 2. Última sessão por matéria
    ultima_sessao = _get_last_session_by_subject(conn)

    # 3-4. Revisões pendentes
    pending = _get_pending_reviews(conn)

    # 5. Progresso do edital
    query_edital = "SELECT COUNT(*) FROM edital WHERE 1=1"
    query_done = "SELECT COUNT(*) FROM edital WHERE status = 'Concluído'"
    params_edital = []
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

    # 6. Dias estudados na semana
    inicio_semana = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    dias_semana = conn.execute("""
        SELECT COUNT(DISTINCT data) FROM streaks
        WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0)
    """, (inicio_semana,)).fetchone()[0]

    # 7. Metas de hoje
    metas = conn.execute("SELECT meta_horas, meta_questoes FROM metas_config WHERE id = 1").fetchone()
    meta_horas = metas[0] if metas else 3.0
    meta_questoes = metas[1] if metas else 30

    hoje_streak = conn.execute("SELECT horas_estudadas, questoes_resolvidas FROM streaks WHERE data = ?", (today_str(),)).fetchone()
    horas_hoje = hoje_streak[0] if hoje_streak else 0
    questoes_hoje = hoje_streak[1] if hoje_streak else 0

    # 8. Streak
    streak_info = calculate_streak(conn)
    streak = streak_info["streak_atual"]

    # 9. Dias até prova
    dias_prova = _dias_ate_prova(conn, edital_nome, cargo)

    # 10. % acerto total
    q_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    q_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]
    pct_acerto_global = (q_acertos / q_total * 100) if q_total > 0 else 0

    # Calcular score de prontidão
    pct_edital = (edital_concluido / edital_total * 100) if edital_total > 0 else 0
    score, nivel = _calculate_readiness_score(pct_acerto_global, pct_edital, dias_semana)

    # Matérias foco
    materias_foco = _get_study_gaps(conn, desempenho, ultima_sessao)

    # Recomendações
    recomendacoes = _generate_recommendations(
        materias_foco, pending, streak, horas_hoje, meta_horas, dias_prova
    )

    log.info(f"Treinador: score={score} nivel={nivel} recomendacoes={len(recomendacoes)}")
    return {
        "score_prontidao": score,
        "nivel": nivel,
        "recomendacoes": recomendacoes,
        "materias_foco": materias_foco,
        "revisoes_pendentes": {"flashcards": pending["flashcards"], "topicos": pending["topicos"]},
        "meta_hoje": {
            "horas": meta_horas,
            "questoes": int(meta_questoes),
            "cumprido_horas": round(horas_hoje, 1),
            "cumprido_questoes": int(questoes_hoje)
        }
    }


@router.get("/api/trilha-diaria", summary="Trilha de Estudo Diária", description="Gera plano de estudo para o dia baseado em revisões pendentes e desempenho")
def trilha_diaria(edital_nome: str = "", cargo: str = "", horas_disponiveis: float = Query(default=3.0), conn=Depends(get_db_session)):
    """Gera trilha de estudo diária personalizada baseada em SM-2 e desempenho"""
    tempo_total_min = int(horas_disponiveis * 60)
    tempo_restante = tempo_total_min
    atividades = []
    ordem = 1

    # 1. Revisões SRS pendentes (flashcards) — prioridade máxima
    pending = _get_pending_reviews(conn)

    if pending["flashcards"] > 0 and tempo_restante > 0:
        tempo_flash = min(max(5, pending["flashcards"] * 2), 20)  # 2min por card, max 20min
        tempo_flash = min(tempo_flash, tempo_restante)
        atividades.append({
            "ordem": ordem,
            "tipo": "revisao",
            "descricao": f"Revisar {pending['flashcards']} flashcard{'s' if pending['flashcards'] > 1 else ''} pendente{'s' if pending['flashcards'] > 1 else ''}",
            "tempo_min": tempo_flash
        })
        tempo_restante -= tempo_flash
        ordem += 1

    # 2. Revisões SRS pendentes (tópicos do edital)
    if pending["topicos"] > 0 and tempo_restante > 0:
        tempo_top = min(max(5, pending["topicos"] * 5), 30)  # 5min por tópico, max 30min
        tempo_top = min(tempo_top, tempo_restante)
        atividades.append({
            "ordem": ordem,
            "tipo": "revisao",
            "descricao": f"Revisar {pending['topicos']} tópico{'s' if pending['topicos'] > 1 else ''} com baixa retenção",
            "tempo_min": tempo_top
        })
        tempo_restante -= tempo_top
        ordem += 1

    # 3. Identificar matérias prioritárias
    desempenho = _get_performance_by_subject(conn)
    ultima_sessao = _get_last_session_by_subject(conn)
    top_materias = _get_priority_activities(conn, desempenho, ultima_sessao, edital_nome, cargo)

    # 4. Distribuir tempo restante entre matérias prioritárias
    new_atividades, ordem = _distribute_time(conn, top_materias, tempo_restante, ordem, edital_nome, cargo)
    atividades.extend(new_atividades)

    # Calcular tempo total real
    tempo_total_real = sum(a["tempo_min"] for a in atividades)

    # Foco principal
    foco_principal = top_materias[0]["materia"] if top_materias else "Revisão"
    motivo = ""
    if top_materias:
        m = top_materias[0]
        motivos = []
        if m["pct"] > 0:
            motivos.append(f"Menor % de acerto ({m['pct']}%)")
        if m["dias_sem"] > 0:
            motivos.append(f"{m['dias_sem']} dias sem estudar")
        dias_prova = _dias_ate_prova(conn, edital_nome, cargo) if edital_nome else None
        if dias_prova is not None:
            motivos.append(f"prova em {dias_prova} dias")
        motivo = " + ".join(motivos) if motivos else "Matéria prioritária"

    log.info(f"Trilha diária gerada: {len(atividades)} atividades, {tempo_total_real}min, foco={foco_principal}")
    return {
        "data": today_str(),
        "horas_disponiveis": horas_disponiveis,
        "atividades": atividades,
        "tempo_total_min": tempo_total_real,
        "foco_principal": foco_principal,
        "motivo": motivo
    }


# ============================================================
# CALENDÁRIO SEMANAL
# ============================================================

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


def _get_materias_edital_with_topics(conn, edital_nome: str = "", cargo: str = "") -> List[dict]:
    """Busca matérias do edital com contagem de tópicos não concluídos e desempenho."""
    query = """
        SELECT materia, COUNT(*) as total_topicos,
               SUM(CASE WHEN status != 'Concluído' THEN 1 ELSE 0 END) as pendentes
        FROM edital WHERE 1=1
    """
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " GROUP BY materia HAVING pendentes > 0 ORDER BY pendentes DESC"
    rows = conn.execute(query, params).fetchall()
    return [{"materia": r[0], "total_topicos": r[1], "pendentes": r[2]} for r in rows]


def _get_uncompleted_topics(conn, materia: str, edital_nome: str = "", cargo: str = "", limit: int = 3) -> list:
    """Busca tópicos não concluídos de uma matéria."""
    query = "SELECT topico FROM edital WHERE materia = ? AND status != 'Concluído'"
    params = [materia]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += f" LIMIT {limit}"
    return [r[0] for r in conn.execute(query, params).fetchall()]


def _distribute_materias_to_days(materias_ranked: List[dict], num_days: int = 7) -> List[List[dict]]:
    """
    Distribui matérias nos dias da semana (2 por dia, exceto domingo).
    Garante alternância: mesma matéria não aparece em dias consecutivos.
    """
    if not materias_ranked:
        return [[] for _ in range(num_days)]

    # Se temos poucas matérias, duplicar para preencher
    materias_pool = materias_ranked[:]
    if len(materias_pool) == 1:
        # Só 1 matéria: usa ela todos os dias
        return [[materias_pool[0]] for _ in range(num_days)]

    days = [[] for _ in range(num_days)]
    # Dias 0-5 (Seg-Sáb): 2 matérias cada; Dia 6 (Domingo): dia leve
    slots_per_day = [2, 2, 2, 2, 2, 2, 0]  # Domingo sem matérias novas

    # Criar ciclo de matérias priorizadas
    # Matérias com pior desempenho aparecem mais vezes
    weighted_pool = []
    for i, m in enumerate(materias_pool):
        # Mais prioritárias ganham mais slots
        repeats = max(1, 3 - i) if i < 4 else 1
        weighted_pool.extend([m] * repeats)

    # Distribuir garantindo alternância
    last_day_materias = set()
    pool_idx = 0

    for day_idx in range(num_days - 1):  # Excluir domingo
        day_materias = []
        attempts = 0
        search_idx = pool_idx

        while len(day_materias) < slots_per_day[day_idx] and attempts < len(weighted_pool) * 2:
            candidate = weighted_pool[search_idx % len(weighted_pool)]
            cand_name = candidate["materia"]

            # Verificar alternância: não repetir do dia anterior
            if cand_name not in last_day_materias and cand_name not in [m["materia"] for m in day_materias]:
                day_materias.append(candidate)
                pool_idx = (search_idx + 1) % len(weighted_pool)

            search_idx += 1
            attempts += 1

        # Se não conseguiu preencher (poucas matérias), relaxar restrição
        if len(day_materias) < slots_per_day[day_idx]:
            for m in materias_pool:
                if m["materia"] not in [dm["materia"] for dm in day_materias]:
                    day_materias.append(m)
                    if len(day_materias) >= slots_per_day[day_idx]:
                        break

        days[day_idx] = day_materias
        last_day_materias = {m["materia"] for m in day_materias}

    return days


@router.get("/api/calendario-semanal", summary="Calendário Semanal", description="Gera programação semanal de estudos baseada em desempenho e edital")
def calendario_semanal(edital_nome: str = "", cargo: str = "", horas_dia: float = Query(default=3.0), conn=Depends(get_db_session)):
    """Gera calendário semanal de estudos com distribuição inteligente de matérias."""
    tempo_dia_min = int(horas_dia * 60)

    # 1. Buscar matérias do edital com tópicos pendentes
    materias_edital = _get_materias_edital_with_topics(conn, edital_nome, cargo)

    if not materias_edital:
        # Sem matérias: retornar calendário vazio com orientação
        hoje = date.today()
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        return {
            "semana_inicio": inicio_semana.isoformat(),
            "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
            "horas_dia": horas_dia,
            "dias": [{
                "dia_semana": i,
                "nome": NOMES_DIAS[i],
                "data": (inicio_semana + timedelta(days=i)).isoformat(),
                "atividades": [{"tipo": "revisao", "descricao": "Adicione matérias ao edital para gerar o calendário", "tempo_min": 0, "materia": None}],
                "tempo_total_min": 0,
                "materias": []
            } for i in range(7)],
            "resumo": {"total_materias": 0, "horas_semana": 0, "distribuicao": []}
        }

    # 2. Obter desempenho por matéria
    desempenho = _get_performance_by_subject(conn)

    # 3. Rankear matérias: pior desempenho + mais tópicos pendentes = mais prioridade
    for m in materias_edital:
        perf = desempenho.get(m["materia"], {})
        pct = perf.get("pct", 0)
        # Score: menor % de acerto = prioridade maior; mais pendentes = prioridade maior
        m["pct_acerto"] = pct
        m["score"] = (100 - pct) + m["pendentes"] * 2

    materias_edital.sort(key=lambda x: -x["score"])

    # 4. Distribuir matérias nos dias
    days_materias = _distribute_materias_to_days(materias_edital)

    # 5. Revisões SRS pendentes
    pending = _get_pending_reviews(conn)

    # 6. Montar calendário
    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())
    dias = []
    distribuicao_map = {}  # materia -> set of day indices

    for day_idx in range(7):
        data_dia = inicio_semana + timedelta(days=day_idx)
        atividades = []
        tempo_restante = tempo_dia_min
        materias_do_dia = []

        # Domingo = dia leve
        is_domingo = day_idx == 6

        # Revisão de flashcards no início (todos os dias)
        if pending["flashcards"] > 0:
            tempo_flash = min(10, tempo_restante)
            atividades.append({
                "tipo": "revisao",
                "descricao": f"Revisar {pending['flashcards']} flashcards pendentes",
                "tempo_min": tempo_flash,
                "materia": None
            })
            tempo_restante -= tempo_flash

        if is_domingo:
            # Domingo: só revisão + questões das matérias mais fracas
            if tempo_restante > 0 and pending["topicos"] > 0:
                tempo_top = min(15, tempo_restante)
                atividades.append({
                    "tipo": "revisao",
                    "descricao": f"Revisar {pending['topicos']} tópicos com baixa retenção",
                    "tempo_min": tempo_top,
                    "materia": None
                })
                tempo_restante -= tempo_top

            # Questões das matérias mais fracas
            weakest = materias_edital[:2] if len(materias_edital) >= 2 else materias_edital
            for mat_info in weakest:
                if tempo_restante < 20:
                    break
                tempo_questoes = min(30, tempo_restante)
                qtd = max(5, tempo_questoes // 2)
                atividades.append({
                    "tipo": "questoes",
                    "materia": mat_info["materia"],
                    "qtd": qtd,
                    "tempo_min": tempo_questoes
                })
                materias_do_dia.append(mat_info["materia"])
                tempo_restante -= tempo_questoes

            # Revisão final
            if tempo_restante >= 10:
                atividades.append({
                    "tipo": "revisao",
                    "descricao": "Revisão geral da semana",
                    "tempo_min": min(15, tempo_restante),
                    "materia": None
                })
                tempo_restante -= min(15, tempo_restante)
        else:
            # Dias normais: estudo + questões por matéria
            day_mats = days_materias[day_idx]
            if not day_mats:
                day_mats = materias_edital[:2]

            num_materias = len(day_mats)
            if num_materias == 0:
                num_materias = 1

            # Reservar tempo para revisão final
            tempo_revisao_final = 10
            tempo_para_materias = tempo_restante - tempo_revisao_final

            # Distribuir tempo entre matérias
            tempo_por_materia = tempo_para_materias // num_materias if num_materias > 0 else 0

            for mat_info in day_mats:
                if tempo_para_materias <= 0:
                    break

                materia_nome = mat_info["materia"]
                materias_do_dia.append(materia_nome)

                # Track distribuição
                if materia_nome not in distribuicao_map:
                    distribuicao_map[materia_nome] = {"dias": [], "tempo_total": 0}
                distribuicao_map[materia_nome]["dias"].append(day_idx)

                # Buscar tópicos
                topicos = _get_uncompleted_topics(conn, materia_nome, edital_nome, cargo, limit=3)
                if not topicos:
                    topicos = ["Revisão geral"]

                # Tempo de estudo (60% do tempo da matéria)
                tempo_estudo = int(tempo_por_materia * 0.6)
                tempo_questoes = int(tempo_por_materia * 0.3)

                if tempo_estudo >= 15:
                    atividades.append({
                        "tipo": "estudo",
                        "materia": materia_nome,
                        "topicos": topicos,
                        "tempo_min": tempo_estudo
                    })

                if tempo_questoes >= 10:
                    qtd_questoes = max(5, tempo_questoes // 2)
                    atividades.append({
                        "tipo": "questoes",
                        "materia": materia_nome,
                        "qtd": qtd_questoes,
                        "tempo_min": tempo_questoes
                    })

                distribuicao_map[materia_nome]["tempo_total"] += tempo_estudo + tempo_questoes
                tempo_para_materias -= (tempo_estudo + tempo_questoes)

            # Revisão final (Técnica Feynman)
            if tempo_revisao_final > 0:
                atividades.append({
                    "tipo": "revisao",
                    "descricao": "Resumo do dia (Técnica Feynman)",
                    "tempo_min": tempo_revisao_final,
                    "materia": None
                })

        tempo_total_dia = sum(a["tempo_min"] for a in atividades)
        dias.append({
            "dia_semana": day_idx,
            "nome": NOMES_DIAS[day_idx],
            "data": data_dia.isoformat(),
            "atividades": atividades,
            "tempo_total_min": tempo_total_dia,
            "materias": materias_do_dia
        })

    # 7. Montar resumo
    distribuicao = []
    for materia, info in distribuicao_map.items():
        horas_semana = round(info["tempo_total"] * len(info["dias"]) / 60, 1)
        # Recalcular baseado no tempo real alocado
        tempo_total_materia = sum(
            a["tempo_min"]
            for d in dias
            for a in d["atividades"]
            if a.get("materia") == materia
        )
        distribuicao.append({
            "materia": materia,
            "dias": sorted(set(info["dias"])),
            "horas_semana": round(tempo_total_materia / 60, 1)
        })

    distribuicao.sort(key=lambda x: -x["horas_semana"])

    horas_semana_total = round(sum(d["tempo_total_min"] for d in dias) / 60, 1)

    log.info(f"Calendário semanal gerado: {len(materias_edital)} matérias, {horas_semana_total}h/semana")
    return {
        "semana_inicio": inicio_semana.isoformat(),
        "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
        "horas_dia": horas_dia,
        "dias": dias,
        "resumo": {
            "total_materias": len(set(m["materia"] for m in materias_edital)),
            "horas_semana": horas_semana_total,
            "distribuicao": distribuicao
        }
    }

import re
from datetime import date, datetime, timedelta
from typing import List

from fastapi import APIRouter, Body, Depends, Query

from constants import WEIGHT_ACCURACY, WEIGHT_CONSISTENCY, WEIGHT_PROGRESS
from database import get_db_session
from logger import log
from models import CalendarioItem
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
    Distribui matérias nos dias da semana com INTERCALAÇÃO FORÇADA.
    - Mesma matéria NUNCA em dias consecutivos
    - Peso por dificuldade: menor % acerto = mais tempo/frequência
    - 2-3 matérias por dia para variedade cognitiva
    """
    if not materias_ranked:
        return [[] for _ in range(num_days)]

    if len(materias_ranked) == 1:
        return [[materias_ranked[0]] for _ in range(num_days)]

    days = [[] for _ in range(num_days)]
    slots_per_day = [2, 3, 2, 3, 2, 2, 0]  # Varia entre 2-3, domingo leve

    # Calcular peso por dificuldade (menor acerto = mais frequência)
    for m in materias_ranked:
        pct = m.get("pct_acerto", 50)
        # Score de dificuldade: 0-100 invertido + boost por pendentes
        m["peso_dificuldade"] = (100 - pct) + min(m.get("pendentes", 0), 20) * 2

    # Ordenar por peso de dificuldade (mais difícil primeiro)
    materias_ranked.sort(key=lambda x: -x.get("peso_dificuldade", x.get("score", 0)))

    # Criar pool com repetições baseadas no peso
    # Top 30% das matérias aparecem ~3x/semana, restante ~1-2x
    total_mats = len(materias_ranked)
    pool = []
    for i, m in enumerate(materias_ranked):
        if i < total_mats * 0.3:
            repeats = 3  # Matérias difíceis: 3x/semana
        elif i < total_mats * 0.6:
            repeats = 2  # Médias: 2x/semana
        else:
            repeats = 1  # Fáceis: 1x/semana
        pool.extend([m] * repeats)

    # Distribuir com INTERCALAÇÃO FORÇADA
    last_day_set = set()
    pool_idx = 0

    for day_idx in range(num_days - 1):  # Excluir domingo
        day_materias = []
        used_this_day = set()
        attempts = 0
        search_idx = pool_idx

        target_slots = slots_per_day[day_idx]

        while len(day_materias) < target_slots and attempts < len(pool) * 3:
            candidate = pool[search_idx % len(pool)]
            cand_name = candidate["materia"]

            # INTERCALAÇÃO FORÇADA: não repetir do dia anterior NEM no mesmo dia
            if cand_name not in last_day_set and cand_name not in used_this_day:
                day_materias.append(candidate)
                used_this_day.add(cand_name)
                pool_idx = (search_idx + 1) % len(pool)

            search_idx += 1
            attempts += 1

        # Fallback: se não preencheu, relaxar restrição de dia anterior
        if len(day_materias) < target_slots:
            for m in materias_ranked:
                if m["materia"] not in used_this_day:
                    day_materias.append(m)
                    used_this_day.add(m["materia"])
                    if len(day_materias) >= target_slots:
                        break

        days[day_idx] = day_materias
        last_day_set = used_this_day

    return days


@router.get("/api/calendario-semanal", summary="Calendário Semanal", description="Gera programação semanal de estudos baseada no planejador inteligente")
def calendario_semanal(edital_nome: str = "", cargo: str = "", horas_dia: float = Query(default=3.0), conn=Depends(get_db_session)):
    """Gera calendário semanal de estudos. Cascata:
    Calendário → verifica Planejador → se vazio gera → verifica Ciclo → se vazio gera dos editais.
    """
    tempo_dia_min = int(horas_dia * 60)

    # 1. CASCATA: Verificar Planejador → se vazio, gerar (que por sua vez gera Ciclo se necessário)
    planejador = conn.execute("SELECT * FROM planejador_semanal ORDER BY dia_semana, id").fetchall()

    planejador_gerado = False
    ciclo_gerado = False
    if not planejador:
        # Gerar planejador automaticamente (que gera ciclo se necessário)
        from routers.misc import gerar_planejador as _gerar_plan_fn
        # Simular a chamada interna (não HTTP)
        _gerar_planejador_interno(conn, horas_dia)
        planejador = conn.execute("SELECT * FROM planejador_semanal ORDER BY dia_semana, id").fetchall()
        planejador_gerado = True

    if not planejador:
        # Se mesmo após geração não há nada (edital vazio)
        hoje = date.today()
        inicio_semana = hoje - timedelta(days=hoje.weekday())
        return {
            "semana_inicio": inicio_semana.isoformat(),
            "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
            "horas_dia": horas_dia,
            "planejador_gerado": False,
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

    # 2. Agrupar planejador por dia
    plan_por_dia = {i: [] for i in range(7)}
    for p in planejador:
        plan_por_dia[p["dia_semana"]].append({"materia": p["materia"], "horas": p["horas"]})

    # 3. Obter desempenho e revisões pendentes
    desempenho = _get_performance_by_subject(conn)
    pending = _get_pending_reviews(conn)

    # 4. Montar calendário enriquecido a partir do planejador
    hoje = date.today()
    inicio_semana = hoje - timedelta(days=hoje.weekday())
    dias = []
    distribuicao_map = {}

    for day_idx in range(7):
        data_dia = inicio_semana + timedelta(days=day_idx)
        atividades = []
        tempo_restante = tempo_dia_min
        materias_do_dia = []
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

        # Usar matérias do planejador para este dia
        day_plan = plan_por_dia.get(day_idx, [])

        if is_domingo and not day_plan:
            # Domingo sem planejamento: revisão leve
            if pending["topicos"] > 0:
                tempo_top = min(15, tempo_restante)
                atividades.append({
                    "tipo": "revisao",
                    "descricao": f"Revisar {pending['topicos']} tópicos com baixa retenção",
                    "tempo_min": tempo_top,
                    "materia": None
                })
                tempo_restante -= tempo_top
            if tempo_restante >= 10:
                atividades.append({
                    "tipo": "revisao",
                    "descricao": "Revisão geral da semana",
                    "tempo_min": min(15, tempo_restante),
                    "materia": None
                })
                tempo_restante -= min(15, tempo_restante)
        elif day_plan:
            # Reservar tempo para revisão final
            tempo_revisao_final = 10
            tempo_para_materias = tempo_restante - tempo_revisao_final
            num_materias = len(day_plan)

            for slot in day_plan:
                if tempo_para_materias <= 0:
                    break

                materia_nome = slot["materia"]
                materias_do_dia.append(materia_nome)

                # Track distribuição
                if materia_nome not in distribuicao_map:
                    distribuicao_map[materia_nome] = {"dias": [], "tempo_total": 0}
                distribuicao_map[materia_nome]["dias"].append(day_idx)

                # Calcular tempo proporcional às horas alocadas no planejador
                total_horas_dia = sum(s["horas"] for s in day_plan) or 1
                proporcao = slot["horas"] / total_horas_dia
                tempo_materia = int(tempo_para_materias * proporcao)

                # Buscar tópicos pendentes
                topicos = _get_uncompleted_topics(conn, materia_nome, edital_nome, cargo, limit=3)
                if not topicos:
                    topicos = ["Revisão geral"]

                # Distribuir: 60% estudo, 30% questões, 10% revisão rápida
                tempo_estudo = int(tempo_materia * 0.6)
                tempo_questoes = int(tempo_materia * 0.3)

                # Matérias com pior desempenho = mais questões, menos teoria
                perf = desempenho.get(materia_nome, {})
                pct = perf.get("pct", 0)
                if pct < 50 and perf.get("total", 0) > 0:
                    # Fraca: mais questões para praticar
                    tempo_estudo = int(tempo_materia * 0.45)
                    tempo_questoes = int(tempo_materia * 0.45)
                elif pct > 80:
                    # Forte: mais teoria para avançar, menos questões
                    tempo_estudo = int(tempo_materia * 0.7)
                    tempo_questoes = int(tempo_materia * 0.2)

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

    # 5. Montar resumo
    distribuicao = []
    for materia, info in distribuicao_map.items():
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
    total_materias = len(set(m for d in dias for m in d["materias"]))

    log.info(f"Calendário semanal gerado: {total_materias} matérias, {horas_semana_total}h/semana (planejador_gerado={planejador_gerado})")
    return {
        "semana_inicio": inicio_semana.isoformat(),
        "semana_fim": (inicio_semana + timedelta(days=6)).isoformat(),
        "horas_dia": horas_dia,
        "planejador_gerado": planejador_gerado,
        "dias": dias,
        "resumo": {
            "total_materias": total_materias,
            "horas_semana": horas_semana_total,
            "distribuicao": distribuicao
        }
    }


def _gerar_planejador_interno(conn, horas_dia: float = 3.0):
    """Gera planejador internamente (sem HTTP). Cascata: gera ciclo se necessário."""
    from routers.ciclo import _gerar_ciclo_automatico

    # Verificar ciclo
    ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 ORDER BY ordem, id").fetchall()
    if not ciclo:
        _gerar_ciclo_automatico(conn, horas_dia)
        ciclo = conn.execute("SELECT * FROM ciclo_estudos WHERE ativo = 1 ORDER BY ordem, id").fetchall()

    if not ciclo:
        return  # Sem matérias no edital

    # Scoring por matéria
    materias_scored = []
    for c in ciclo:
        mat = c["materia"]
        desemp = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
            WHERE q.materia = ?
        """, (mat,)).fetchone()
        total_q = desemp[0] or 0
        pct_acerto = (desemp[1] / total_q * 100) if total_q > 0 else 0

        horas_estudadas = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ?", (mat,)
        ).fetchone()[0]

        pendentes = conn.execute(
            "SELECT COUNT(*) FROM edital WHERE materia = ? AND status != 'Concluído' AND arquivado = 0", (mat,)
        ).fetchone()[0]

        ultima = conn.execute("SELECT MAX(data) FROM sessoes_estudo WHERE materia = ?", (mat,)).fetchone()[0]
        if ultima:
            try:
                dias_sem = (date.today() - date.fromisoformat(ultima)).days
            except (ValueError, TypeError):
                dias_sem = 30
        else:
            dias_sem = 999

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

    # Frequência por tier
    total_mats = len(materias_scored)
    for i, m in enumerate(materias_scored):
        pos = i / max(total_mats, 1)
        m["freq"] = 3 if pos < 0.3 else 2 if pos < 0.65 else 1

    # Distribuir em 6 dias
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

    # Domingo revisão
    for m in materias_scored[:2]:
        dias[6].append({"materia": m["materia"], "horas": 0.5})

    # Salvar
    conn.execute("DELETE FROM planejador_semanal")
    for dia_idx, slots in enumerate(dias):
        for slot in slots:
            conn.execute("INSERT INTO planejador_semanal (dia_semana, materia, horas) VALUES (?, ?, ?)",
                         (dia_idx, slot["materia"], slot["horas"]))
    conn.commit()


# ============================================================
# CALENDÁRIO PERSONALIZADO
# ============================================================


@router.get("/api/calendario-personalizado")
def get_calendario_personalizado(conn=Depends(get_db_session)):
    """Retorna o calendário personalizado salvo pelo usuário."""
    rows = conn.execute(
        "SELECT id, dia_semana, materia, topicos, tempo_min, tipo, ordem FROM calendario_personalizado ORDER BY dia_semana, ordem"
    ).fetchall()
    items = [dict(r) for r in rows]
    # Agrupar por dia
    dias_nomes = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]
    dias = []
    for d in range(7):
        atividades = [i for i in items if i["dia_semana"] == d]
        tempo_total = sum(a["tempo_min"] for a in atividades)
        materias = list(set(a["materia"] for a in atividades if a["materia"]))
        dias.append({
            "dia_semana": d,
            "nome": dias_nomes[d],
            "atividades": atividades,
            "tempo_total_min": tempo_total,
            "materias": materias
        })
    return {"dias": dias}


@router.post("/api/calendario-personalizado")
def add_calendario_item(body: CalendarioItem, conn=Depends(get_db_session)):
    """Adiciona uma atividade ao calendário personalizado."""
    cur = conn.execute(
        "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem) VALUES (?, ?, ?, ?, ?, ?)",
        (body.dia_semana, body.materia, body.topicos, body.tempo_min, body.tipo, body.ordem)
    )
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/calendario-personalizado/{id}")
def delete_calendario_item(id: int, conn=Depends(get_db_session)):
    """Remove uma atividade do calendário personalizado."""
    conn.execute("DELETE FROM calendario_personalizado WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}


@router.delete("/api/calendario-personalizado")
def clear_calendario_personalizado(conn=Depends(get_db_session)):
    """Limpa todo o calendário personalizado."""
    conn.execute("DELETE FROM calendario_personalizado")
    conn.commit()
    return {"ok": True}


@router.post("/api/calendario-personalizado/salvar-completo")
def salvar_calendario_completo(dias: list = Body(...), conn=Depends(get_db_session)):
    """Salva o calendário completo (limpa e recria). Body: array de {dia_semana, materia, topicos, tempo_min, tipo, ordem}"""
    conn.execute("DELETE FROM calendario_personalizado")
    count = 0
    for item in dias:
        conn.execute(
            "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem) VALUES (?, ?, ?, ?, ?, ?)",
            (item.get("dia_semana", 0), item.get("materia", ""), item.get("topicos", ""),
             item.get("tempo_min", 60), item.get("tipo", "estudo"), item.get("ordem", count))
        )
        count += 1
    conn.commit()
    return {"ok": True, "salvos": count}



# ============================================================
# ATIVIDADES DO CALENDÁRIO - CONCLUSÃO + STREAK
# ============================================================

@router.post("/api/calendario/atividade-concluida")
def marcar_atividade_concluida(body: dict = Body(...), conn=Depends(get_db_session)):
    """Marca uma atividade do calendário como concluída.
    Body: {data, dia_semana, materia, tipo, tempo_min}
    """
    data_str = body.get("data", today_str())
    dia_semana = body.get("dia_semana", 0)
    materia = body.get("materia", "")
    tipo = body.get("tipo", "estudo")
    tempo_min = body.get("tempo_min", 0)

    conn.execute("""
        INSERT INTO calendario_atividades (data, dia_semana, materia, tipo, tempo_min, concluida, concluida_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (data_str, dia_semana, materia, tipo, tempo_min, datetime.now().isoformat()))

    # Atualizar streak do calendário
    _update_calendario_streak(conn, data_str, body.get("total_atividades", 0))

    conn.commit()
    log.info(f"Atividade concluída: {materia} ({tipo}) em {data_str}")
    return {"ok": True}


@router.delete("/api/calendario/atividade-concluida")
def desmarcar_atividade_concluida(body: dict = Body(...), conn=Depends(get_db_session)):
    """Desmarca uma atividade (desfaz conclusão)."""
    data_str = body.get("data", today_str())
    materia = body.get("materia", "")
    tipo = body.get("tipo", "estudo")

    conn.execute("""
        DELETE FROM calendario_atividades
        WHERE data = ? AND materia = ? AND tipo = ?
        ORDER BY id DESC LIMIT 1
    """, (data_str, materia, tipo))

    _update_calendario_streak(conn, data_str, body.get("total_atividades", 0))
    conn.commit()
    return {"ok": True}


@router.get("/api/calendario/concluidas")
def get_atividades_concluidas(data: str = "", conn=Depends(get_db_session)):
    """Retorna atividades concluídas de um dia (ou hoje)."""
    data_str = data or today_str()
    rows = conn.execute(
        "SELECT * FROM calendario_atividades WHERE data = ? AND concluida = 1",
        (data_str,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/calendario/streak")
def get_calendario_streak(conn=Depends(get_db_session)):
    """Retorna streak de dias com 100% do calendário concluído."""
    rows = conn.execute("""
        SELECT data, pct_conclusao FROM calendario_streaks
        WHERE pct_conclusao >= 100
        ORDER BY data DESC
    """).fetchall()

    # Calcular streak consecutivo
    streak = 0
    hoje = date.today()
    for i, r in enumerate(rows):
        expected = (hoje - timedelta(days=i)).isoformat()
        if r[0] == expected:
            streak += 1
        else:
            break

    # Melhor streak
    best = 0
    current = 0
    all_dates = [r[0] for r in rows]
    all_dates.sort()
    for i, d in enumerate(all_dates):
        if i == 0:
            current = 1
        else:
            prev = date.fromisoformat(all_dates[i-1])
            curr = date.fromisoformat(d)
            if (curr - prev).days == 1:
                current += 1
            else:
                current = 1
        best = max(best, current)

    # Progresso de hoje
    hoje_row = conn.execute(
        "SELECT * FROM calendario_streaks WHERE data = ?", (today_str(),)
    ).fetchone()

    return {
        "streak_calendario": streak,
        "melhor_streak_calendario": best,
        "hoje": dict(hoje_row) if hoje_row else {"total_atividades": 0, "concluidas": 0, "pct_conclusao": 0}
    }


def _update_calendario_streak(conn, data_str: str, total_atividades: int = 0):
    """Atualiza o registro de streak do calendário para uma data."""
    concluidas = conn.execute(
        "SELECT COUNT(*) FROM calendario_atividades WHERE data = ? AND concluida = 1",
        (data_str,)
    ).fetchone()[0]

    pct = round((concluidas / total_atividades * 100) if total_atividades > 0 else 0, 1)
    xp = 50 if pct >= 100 else 0  # XP bônus por 100%

    conn.execute("""
        INSERT INTO calendario_streaks (data, total_atividades, concluidas, pct_conclusao, xp_bonus)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(data) DO UPDATE SET
            total_atividades = ?, concluidas = ?, pct_conclusao = ?, xp_bonus = ?
    """, (data_str, total_atividades, concluidas, pct, xp,
          total_atividades, concluidas, pct, xp))


# ============================================================
# ALERTA DE MATÉRIAS NEGLIGENCIADAS
# ============================================================

@router.get("/api/calendario/materias-negligenciadas")
def get_materias_negligenciadas(dias_limite: int = 5, conn=Depends(get_db_session)):
    """Retorna matérias importantes que não foram estudadas há mais de X dias."""
    hoje = date.today()

    # Buscar matérias do edital com seus pesos (tópicos pendentes)
    materias = conn.execute("""
        SELECT materia, COUNT(*) as pendentes
        FROM edital WHERE status != 'Concluído'
        GROUP BY materia HAVING pendentes > 3
        ORDER BY pendentes DESC
    """).fetchall()

    # Buscar última sessão de estudo por matéria
    sessoes = conn.execute("""
        SELECT materia, MAX(data) as ultima FROM sessoes_estudo GROUP BY materia
    """).fetchall()
    ultima_sessao = {r[0]: r[1] for r in sessoes}

    # Buscar última atividade concluída no calendário por matéria
    cal_atividades = conn.execute("""
        SELECT materia, MAX(data) as ultima FROM calendario_atividades
        WHERE concluida = 1 AND materia != ''
        GROUP BY materia
    """).fetchall()
    ultima_cal = {r[0]: r[1] for r in cal_atividades}

    negligenciadas = []
    for r in materias:
        materia = r[0]
        pendentes = r[1]

        # Pegar a data mais recente entre sessão de estudo e atividade do calendário
        ultima_estudo = ultima_sessao.get(materia)
        ultima_ativ = ultima_cal.get(materia)

        if ultima_estudo and ultima_ativ:
            ultima = max(ultima_estudo, ultima_ativ)
        elif ultima_estudo:
            ultima = ultima_estudo
        elif ultima_ativ:
            ultima = ultima_ativ
        else:
            ultima = None

        if ultima:
            dias_sem = (hoje - date.fromisoformat(ultima)).days
        else:
            dias_sem = 999  # Nunca estudou

        if dias_sem >= dias_limite:
            # Buscar desempenho
            perf = conn.execute("""
                SELECT COUNT(*) as total, SUM(qr.acertou) as acertos
                FROM questoes_respostas qr
                JOIN questoes q ON q.id = qr.questao_id
                WHERE q.materia = ?
            """, (materia,)).fetchone()

            pct_acerto = round((perf[1] or 0) / perf[0] * 100, 1) if perf[0] and perf[0] > 0 else 0

            negligenciadas.append({
                "materia": materia,
                "dias_sem_estudar": dias_sem,
                "topicos_pendentes": pendentes,
                "pct_acerto": pct_acerto,
                "urgencia": "alta" if dias_sem > 10 or (dias_sem > 5 and pct_acerto < 60) else "media",
                "sugestao": f"Estudar {min(3, pendentes)} tópicos + resolver {max(5, 10 - pct_acerto // 10)} questões"
            })

    negligenciadas.sort(key=lambda x: (-1 if x["urgencia"] == "alta" else 0, -x["dias_sem_estudar"]))
    return {
        "negligenciadas": negligenciadas,
        "total": len(negligenciadas),
        "dias_limite": dias_limite
    }



# ============================================================
# MICRO-REVISÕES (2-MIN DRILLS)
# ============================================================

@router.get("/api/micro-revisao")
def get_micro_revisao(quantidade: int = 5, conn=Depends(get_db_session)):
    """Gera sessão ultra-curta de micro-revisão: 3-5 perguntas rápidas aleatórias."""
    # Misturar flashcards e tópicos do edital
    items = []

    # Flashcards aleatórios
    flashcards = conn.execute(
        "SELECT id, pergunta, resposta, materia FROM flashcards ORDER BY RANDOM() LIMIT ?",
        (quantidade,)
    ).fetchall()
    for f in flashcards:
        items.append({
            "tipo": "flashcard",
            "id": f[0],
            "pergunta": f[1],
            "resposta": f[2],
            "materia": f[3] or "Geral"
        })

    # Se não tem flashcards suficientes, completar com tópicos do edital
    if len(items) < quantidade:
        falta = quantidade - len(items)
        topicos = conn.execute(
            "SELECT id, materia, topico FROM edital WHERE status != 'Concluído' ORDER BY RANDOM() LIMIT ?",
            (falta,)
        ).fetchall()
        for t in topicos:
            items.append({
                "tipo": "topico",
                "id": t[0],
                "pergunta": f"O que você sabe sobre: {t[2]}?",
                "resposta": f"Tópico de {t[1]} — revise seu material.",
                "materia": t[1]
            })

    import random
    random.shuffle(items)
    return {"items": items[:quantidade], "total": len(items), "tempo_estimado_seg": quantidade * 24}


# ============================================================
# QUESTÕES DISSERTATIVAS
# ============================================================

@router.get("/api/questao-dissertativa")
def get_questao_dissertativa(materia: str = "", conn=Depends(get_db_session)):
    """Gera uma questão dissertativa baseada em tópico do edital."""
    query = "SELECT id, materia, topico FROM edital WHERE status != 'Concluído'"
    params = []
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    query += " ORDER BY RANDOM() LIMIT 1"
    row = conn.execute(query, params).fetchone()

    if not row:
        return {"pergunta": None, "message": "Nenhum tópico disponível."}

    # Gerar pergunta dissertativa baseada no tópico
    topico = row[2]
    materia_nome = row[1]
    edital_id = row[0]

    perguntas_modelo = [
        f"Explique com suas palavras o conceito de '{topico}' em {materia_nome}.",
        f"Quais são os principais aspectos de '{topico}'? Descreva pelo menos 3 pontos.",
        f"Como '{topico}' se relaciona com outros temas de {materia_nome}?",
        f"Dê um exemplo prático de aplicação de '{topico}' em uma prova de concurso.",
        f"Compare e diferencie os elementos principais de '{topico}'.",
    ]

    import random
    pergunta = random.choice(perguntas_modelo)

    return {
        "edital_id": edital_id,
        "materia": materia_nome,
        "topico": topico,
        "pergunta": pergunta,
        "dica": "Escreva sua resposta completa. Quanto mais detalhes, melhor a fixação."
    }


@router.post("/api/questao-dissertativa/salvar")
def salvar_questao_dissertativa(body: dict = Body(...), conn=Depends(get_db_session)):
    """Salva a resposta de uma questão dissertativa."""
    edital_id = body.get("edital_id")
    resposta = body.get("resposta", "")
    confianca = body.get("confianca", 3)  # 1-5

    if not resposta or not edital_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Preencha a resposta.")

    # Salvar como resumo do tópico
    conn.execute(
        "INSERT INTO resumos (edital_id, resumo, tipo, created_at) VALUES (?, ?, 'dissertativa', ?)",
        (edital_id, resposta, today_str())
    )

    # Registrar confiança
    conn.execute("""
        INSERT INTO calendario_atividades (data, dia_semana, materia, tipo, tempo_min, concluida, concluida_at)
        VALUES (?, ?, ?, 'dissertativa', 5, 1, ?)
    """, (today_str(), date.today().weekday(), body.get("materia", ""), datetime.now().isoformat()))

    conn.commit()
    return {"ok": True, "confianca": confianca}


# ============================================================
# AUTOAVALIAÇÃO DE CONFIANÇA
# ============================================================

@router.get("/api/autoavaliacao")
def get_autoavaliacao(quantidade: int = 5, conn=Depends(get_db_session)):
    """Gera sessão de autoavaliação: pergunta + o aluno indica nível de confiança antes de ver a resposta."""
    flashcards = conn.execute(
        "SELECT id, pergunta, resposta, materia FROM flashcards ORDER BY RANDOM() LIMIT ?",
        (quantidade,)
    ).fetchall()

    items = [{
        "id": f[0],
        "pergunta": f[1],
        "resposta": f[2],
        "materia": f[3] or "Geral"
    } for f in flashcards]

    return {"items": items, "instrucao": "Antes de revelar a resposta, indique sua confiança: 1=Não sei, 2=Acho que sei, 3=Tenho certeza"}


@router.post("/api/autoavaliacao/registrar")
def registrar_autoavaliacao(body: dict = Body(...), conn=Depends(get_db_session)):
    """Registra resultado da autoavaliação para calibrar metacognição."""
    resultados = body.get("resultados", [])
    # Cada resultado: {flashcard_id, confianca_pre (1-3), acertou (bool)}

    calibrados = 0
    superconfiante = 0
    subconfiante = 0

    for r in resultados:
        conf = r.get("confianca_pre", 2)
        acertou = r.get("acertou", False)
        fid = r.get("flashcard_id")

        if conf == 3 and not acertou:
            superconfiante += 1  # Achava que sabia, mas errou
        elif conf == 1 and acertou:
            subconfiante += 1  # Achava que não sabia, mas acertou
        elif (conf >= 2 and acertou) or (conf == 1 and not acertou):
            calibrados += 1  # Confiança alinhada com resultado

        # Revisar flashcard se errou
        if fid and not acertou:
            conn.execute(
                "UPDATE flashcards SET proxima_revisao = ?, intervalo_dias = 1 WHERE id = ?",
                (today_str(), fid)
            )

    conn.commit()

    total = len(resultados)
    calibracao_pct = round(calibrados / total * 100) if total > 0 else 0

    return {
        "ok": True,
        "total": total,
        "calibrados": calibrados,
        "superconfiante": superconfiante,
        "subconfiante": subconfiante,
        "calibracao_pct": calibracao_pct,
        "feedback": (
            "🎯 Excelente calibração! Você sabe o que sabe." if calibracao_pct >= 80
            else "⚠️ Cuidado com overconfidence — revise os temas que errou." if superconfiante > subconfiante
            else "💪 Você sabe mais do que pensa! Confie mais no seu conhecimento." if subconfiante > superconfiante
            else "📊 Continue praticando para melhorar sua metacognição."
        )
    }


# ============================================================
# PRÁTICA DISTRIBUÍDA - SPACING INDICATOR
# ============================================================

@router.get("/api/spacing-indicator")
def get_spacing_indicator(conn=Depends(get_db_session)):
    """Retorna indicador de espaçamento: quais matérias estão com distribuição ideal e quais precisam ser mais espaçadas."""
    materias = conn.execute("""
        SELECT materia, COUNT(*) as sessoes, MIN(data) as primeira, MAX(data) as ultima
        FROM sessoes_estudo
        WHERE data >= date('now', '-30 days')
        GROUP BY materia
        HAVING sessoes >= 2
    """).fetchall()

    resultado = []
    hoje = date.today()

    for r in materias:
        materia = r[0]
        sessoes = r[1]
        primeira = r[2]
        ultima = r[3]

        if primeira and ultima and primeira != ultima:
            dias_span = (date.fromisoformat(ultima) - date.fromisoformat(primeira)).days
            intervalo_medio = dias_span / (sessoes - 1) if sessoes > 1 else 0

            # Ideal: 2-4 dias entre sessões (spacing effect)
            if intervalo_medio >= 2 and intervalo_medio <= 4:
                status = "ideal"
                cor = "#a6e3a1"
            elif intervalo_medio < 2:
                status = "muito_junto"
                cor = "#f9e2af"
            else:
                status = "muito_espaco"
                cor = "#f38ba8"

            resultado.append({
                "materia": materia,
                "sessoes_30d": sessoes,
                "intervalo_medio_dias": round(intervalo_medio, 1),
                "status": status,
                "cor": cor,
                "sugestao": (
                    "✅ Espaçamento ideal! Continue assim." if status == "ideal"
                    else "⚠️ Sessões muito juntas — espalhe mais ao longo da semana." if status == "muito_junto"
                    else "🔴 Intervalo muito grande — aumente a frequência."
                )
            })

    resultado.sort(key=lambda x: 0 if x["status"] == "ideal" else (1 if x["status"] == "muito_junto" else 2))
    return {"materias": resultado, "total": len(resultado)}

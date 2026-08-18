import re
from datetime import date, timedelta

from fastapi import APIRouter, Query

from database import get_db
from logger import log
from utils import today_str, calculate_streak

router = APIRouter(prefix="", tags=["Treinador Inteligente"])


def _get_materias_desempenho(conn):
    """Retorna desempenho por matéria (% acerto, total questões)"""
    rows = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
    """).fetchall()
    return {r[0]: {"total": r[1], "acertos": r[2] or 0, "pct": round((r[2] or 0) / r[1] * 100, 1) if r[1] > 0 else 0} for r in rows}


def _get_ultima_sessao_por_materia(conn):
    """Retorna a data da última sessão de estudo por matéria"""
    rows = conn.execute("""
        SELECT materia, MAX(data) as ultima FROM sessoes_estudo GROUP BY materia
    """).fetchall()
    return {r[0]: r[1] for r in rows}


def _dias_ate_prova(conn, edital_nome: str = "", cargo: str = ""):
    """Retorna dias até a próxima prova"""
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
    except Exception:
        pass
    return None


@router.get("/api/treinador", summary="Treinador Inteligente", description="Retorna recomendações de estudo personalizadas baseadas em desempenho e progresso")
def treinador_inteligente(edital_nome: str = "", cargo: str = ""):
    """Treinador inteligente: recomendações baseadas em desempenho, revisões pendentes e metas"""
    with get_db() as conn:
        # 1. Desempenho por matéria
        desempenho = _get_materias_desempenho(conn)

        # 2. Última sessão por matéria
        ultima_sessao = _get_ultima_sessao_por_materia(conn)

        # 3. Revisões pendentes de flashcards
        flashcards_pendentes = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)
        ).fetchone()[0]

        # 4. Revisões pendentes de tópicos do edital
        topicos_pendentes = conn.execute("""
            SELECT COUNT(*) FROM edital
            WHERE proxima_revisao != '' AND proxima_revisao <= ?
        """, (today_str(),)).fetchone()[0]

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

    # ===== CALCULAR SCORE DE PRONTIDÃO =====
    pct_edital = (edital_concluido / edital_total * 100) if edital_total > 0 else 0
    score = (pct_acerto_global * 0.4) + (pct_edital * 0.3) + (dias_semana / 7 * 100 * 0.3)
    score = min(100, max(0, round(score, 1)))

    # Classificação
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

    # ===== MATÉRIAS FOCO =====
    materias_foco = []
    hoje_date = date.today()
    for mat, stats in desempenho.items():
        if stats["total"] >= 5 and stats["pct"] < 70:
            dias_sem = 0
            if mat in ultima_sessao and ultima_sessao[mat]:
                try:
                    ultima = date.fromisoformat(ultima_sessao[mat])
                    dias_sem = (hoje_date - ultima).days
                except (ValueError, TypeError):
                    pass
            prioridade = "ALTA" if stats["pct"] < 50 else "MÉDIA"
            materias_foco.append({
                "materia": mat,
                "pct_acerto": stats["pct"],
                "dias_sem_estudar": dias_sem,
                "prioridade": prioridade
            })

    # Adicionar matérias com muitos dias sem estudar
    for mat, ultima in ultima_sessao.items():
        if mat not in [m["materia"] for m in materias_foco]:
            try:
                dias_sem = (hoje_date - date.fromisoformat(ultima)).days
            except (ValueError, TypeError):
                dias_sem = 0
            if dias_sem >= 7:
                materias_foco.append({
                    "materia": mat,
                    "pct_acerto": desempenho.get(mat, {}).get("pct", 0),
                    "dias_sem_estudar": dias_sem,
                    "prioridade": "MÉDIA" if dias_sem < 14 else "ALTA"
                })

    materias_foco.sort(key=lambda x: (0 if x["prioridade"] == "ALTA" else 1, x.get("pct_acerto", 100)))
    materias_foco = materias_foco[:5]

    # ===== RECOMENDAÇÕES =====
    recomendacoes = []

    # Revisões pendentes
    if flashcards_pendentes > 0:
        recomendacoes.append({
            "tipo": "revisar",
            "msg": f"Revisar {flashcards_pendentes} flashcard{'s' if flashcards_pendentes > 1 else ''} pendente{'s' if flashcards_pendentes > 1 else ''}",
            "acao": "/flashcards"
        })

    if topicos_pendentes > 0:
        recomendacoes.append({
            "tipo": "revisar",
            "msg": f"Revisar {topicos_pendentes} tópico{'s' if topicos_pendentes > 1 else ''} do edital com revisão pendente",
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

    if horas_hoje < meta_horas * 0.5 and hoje_date.hour >= 18 if hasattr(hoje_date, 'hour') else True:
        recomendacoes.append({
            "tipo": "alerta",
            "msg": f"📊 Meta de {meta_horas}h ainda não atingida ({horas_hoje:.1f}h cumpridas)"
        })

    log.info(f"Treinador: score={score} nivel={nivel} recomendacoes={len(recomendacoes)}")
    return {
        "score_prontidao": score,
        "nivel": nivel,
        "recomendacoes": recomendacoes,
        "materias_foco": materias_foco,
        "revisoes_pendentes": {"flashcards": flashcards_pendentes, "topicos": topicos_pendentes},
        "meta_hoje": {
            "horas": meta_horas,
            "questoes": int(meta_questoes),
            "cumprido_horas": round(horas_hoje, 1),
            "cumprido_questoes": int(questoes_hoje)
        }
    }


@router.get("/api/trilha-diaria", summary="Trilha de Estudo Diária", description="Gera plano de estudo para o dia baseado em revisões pendentes e desempenho")
def trilha_diaria(edital_nome: str = "", cargo: str = "", horas_disponiveis: float = Query(default=3.0)):
    """Gera trilha de estudo diária personalizada baseada em SM-2 e desempenho"""
    with get_db() as conn:
        tempo_total_min = int(horas_disponiveis * 60)
        tempo_restante = tempo_total_min
        atividades = []
        ordem = 1

        # 1. Revisões SRS pendentes (flashcards) — prioridade máxima
        flashcards_pendentes = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)
        ).fetchone()[0]

        if flashcards_pendentes > 0 and tempo_restante > 0:
            tempo_flash = min(max(5, flashcards_pendentes * 2), 20)  # 2min por card, max 20min
            tempo_flash = min(tempo_flash, tempo_restante)
            atividades.append({
                "ordem": ordem,
                "tipo": "revisao",
                "descricao": f"Revisar {flashcards_pendentes} flashcard{'s' if flashcards_pendentes > 1 else ''} pendente{'s' if flashcards_pendentes > 1 else ''}",
                "tempo_min": tempo_flash
            })
            tempo_restante -= tempo_flash
            ordem += 1

        # 2. Revisões SRS pendentes (tópicos do edital)
        topicos_pend = conn.execute("""
            SELECT COUNT(*) FROM edital
            WHERE proxima_revisao != '' AND proxima_revisao <= ?
        """, (today_str(),)).fetchone()[0]

        if topicos_pend > 0 and tempo_restante > 0:
            tempo_top = min(max(5, topicos_pend * 5), 30)  # 5min por tópico, max 30min
            tempo_top = min(tempo_top, tempo_restante)
            atividades.append({
                "ordem": ordem,
                "tipo": "revisao",
                "descricao": f"Revisar {topicos_pend} tópico{'s' if topicos_pend > 1 else ''} com baixa retenção",
                "tempo_min": tempo_top
            })
            tempo_restante -= tempo_top
            ordem += 1

        # 3. Identificar matérias prioritárias (pior desempenho + mais tempo sem estudar)
        desempenho = _get_materias_desempenho(conn)
        ultima_sessao = _get_ultima_sessao_por_materia(conn)

        # Classificar matérias por prioridade
        materias_priority = []
        hoje_date = date.today()
        for mat, stats in desempenho.items():
            if stats["total"] >= 3:
                dias_sem = 0
                if mat in ultima_sessao and ultima_sessao[mat]:
                    try:
                        dias_sem = (hoje_date - date.fromisoformat(ultima_sessao[mat])).days
                    except (ValueError, TypeError):
                        pass
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
                dias_sem = 0
                if mat in ultima_sessao and ultima_sessao[mat]:
                    try:
                        dias_sem = (hoje_date - date.fromisoformat(ultima_sessao[mat])).days
                    except (ValueError, TypeError):
                        pass
                materias_priority.append({
                    "materia": mat,
                    "pct": 0,
                    "dias_sem": dias_sem,
                    "score": 100 + dias_sem * 2
                })

        materias_priority.sort(key=lambda x: -x["score"])
        top_materias = materias_priority[:3]

        # 4. Distribuir tempo restante entre matérias prioritárias
        if top_materias and tempo_restante > 0:
            # Distribuir proporcionalmente ao score
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

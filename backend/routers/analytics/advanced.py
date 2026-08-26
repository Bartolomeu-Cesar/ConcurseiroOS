"""Analytics avançados: curva de esquecimento, raio-x, evolução, ROI, weekly wrap."""
import json
import re
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from services import get_acertos_por_materia, get_horas_estudadas
from utils import calculate_streak, today_str

router = APIRouter(prefix="", tags=["Analytics"])



@router.get("/api/curva-esquecimento")
def curva_esquecimento(edital_nome: str = "", cargo: str = "", materia: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = """
        SELECT id, edital_nome, cargo, materia, topico, proxima_revisao,
               intervalo_revisao, easiness_factor_edital
        FROM edital WHERE proxima_revisao != '' AND proxima_revisao IS NOT NULL AND user_id = ?
    """
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    query += " ORDER BY materia, topico"
    rows = conn.execute(query, params).fetchall()

    resultado = []
    hoje = date.today()
    for r in rows:
        proxima_revisao, intervalo, ef = r[5], r[6] or 1, r[7] if r[7] is not None else 2.5
        try:
            prox = date.fromisoformat(proxima_revisao)
            ultima_revisao = prox - timedelta(days=intervalo)
            t = (hoje - ultima_revisao).days
        except (ValueError, TypeError):
            continue
        if t < 0:
            t = 0
        S = intervalo * ef
        if S <= 0:
            S = 1
        # FSRS-5 power-law retrievability: R(t, S) = (1 + t/(9*S))^(-1)
        retencao = (1.0 + t / (9.0 * S)) ** (-1)
        retencao_pct = round(retencao * 100, 1)
        resultado.append({
            "id": r[0], "materia": r[3], "topico": r[4], "retencao_pct": retencao_pct,
            "dias_desde_revisao": t, "proxima_revisao": proxima_revisao, "urgente": retencao_pct < 50
        })

    resultado.sort(key=lambda x: x["retencao_pct"])
    return resultado


@router.get("/api/raio-x")
def raio_x_edital(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Matérias por peso. Fonte primária: edital (tópicos por matéria). Fallback: contagem de questões."""

    # Auto-detectar edital do ciclo ativo se nenhum filtro explícito
    if not edital_nome and not cargo:
        try:
            ciclo_edital = conn.execute("""
                SELECT e.edital_nome, COUNT(DISTINCT e.materia) as matches
                FROM edital e
                INNER JOIN ciclo_estudos c ON c.materia = e.materia AND c.user_id = e.user_id
                WHERE c.ativo = 1 AND c.user_id = ? AND e.arquivado = 0
                GROUP BY e.edital_nome
                ORDER BY matches DESC LIMIT 1
            """, (user_id,)).fetchone()
            if ciclo_edital and ciclo_edital["edital_nome"]:
                edital_nome = ciclo_edital["edital_nome"]
        except Exception:
            pass

    # === 1. Tentar calcular peso pelo edital (fonte oficial) ===
    edital_filter = "AND arquivado = 0"
    edital_params = [user_id]
    if edital_nome:
        edital_filter += " AND edital_nome = ?"
        edital_params.append(edital_nome)
    if cargo:
        edital_filter += " AND cargo = ?"
        edital_params.append(cargo)

    # Filtrar apenas matérias do ciclo ativo (se existir)
    ciclo_materias = conn.execute(
        "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
    ).fetchall()
    if ciclo_materias and not cargo:
        ciclo_mats = [m["materia"] for m in ciclo_materias]
        placeholders = ",".join("?" * len(ciclo_mats))
        edital_filter += f" AND materia IN ({placeholders})"
        edital_params.extend(ciclo_mats)

    edital_materias = conn.execute(
        f"SELECT materia, COUNT(DISTINCT topico) as topicos FROM edital WHERE user_id = ? {edital_filter} GROUP BY materia ORDER BY topicos DESC",
        edital_params
    ).fetchall()

    total_topicos_edital = sum(r["topicos"] for r in edital_materias) if edital_materias else 0
    usar_edital = total_topicos_edital > 0

    # Mapa de peso pelo edital: materia → % de tópicos
    peso_edital_map = {}
    if usar_edital:
        for r in edital_materias:
            peso_edital_map[r["materia"]] = round(r["topicos"] / total_topicos_edital * 100, 1)

    # === 2. Dados de questões (sempre necessário para acertos e horas) ===
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes WHERE user_id = ?", (user_id,)).fetchone()[0]
    questoes_por_mat = conn.execute("SELECT materia, COUNT(*) as qtd FROM questoes WHERE user_id = ? GROUP BY materia ORDER BY qtd DESC", (user_id,)).fetchall()
    questoes_map = {r[0]: r[1] for r in questoes_por_mat}

    horas_por_mat = conn.execute("SELECT materia, SUM(horas) as total FROM sessoes_estudo WHERE user_id = ? GROUP BY materia", (user_id,)).fetchall()
    horas_map = {r[0]: r[1] for r in horas_por_mat}

    acertos_por_mat = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id WHERE qr.user_id = ? GROUP BY q.materia
    """, (user_id,)).fetchall()
    acerto_map = {r[0]: round((r[2] or 0) / r[1] * 100, 1) if r[1] > 0 else 0 for r in acertos_por_mat}
    total_horas = sum(horas_map.values()) if horas_map else 0

    # === 3. Montar resultado: usar edital como base se disponível ===
    materias = []
    todas_materias = set(peso_edital_map.keys()) | set(questoes_map.keys())

    for mat in todas_materias:
        qtd = questoes_map.get(mat, 0)

        # Peso: edital se disponível, senão contagem de questões
        if usar_edital and mat in peso_edital_map:
            peso_pct = peso_edital_map[mat]
            fonte_peso = "edital"
        elif total_questoes > 0 and qtd > 0:
            peso_pct = round(qtd / total_questoes * 100, 1)
            fonte_peso = "questoes"
        else:
            peso_pct = 0
            fonte_peso = "sem_dados"

        horas_est = round(horas_map.get(mat, 0), 1)
        pct_horas = round(horas_est / total_horas * 100, 1) if total_horas > 0 else 0
        pct_acerto = acerto_map.get(mat, 0)

        # Balanceamento: compara tempo investido vs peso da matéria
        if total_horas == 0 or peso_pct == 0:
            balanceamento = "sem_dados"
        elif pct_horas >= peso_pct * 1.5:
            balanceamento = "superestudado"
        elif pct_horas <= peso_pct * 0.5:
            balanceamento = "subestudado"
        else:
            balanceamento = "equilibrado"

        materias.append({
            "materia": mat,
            "questoes": qtd,
            "peso_pct": peso_pct,
            "fonte_peso": fonte_peso,
            "horas_estudadas": horas_est,
            "pct_acerto": pct_acerto,
            "balanceamento": balanceamento,
        })

    # Ordenar por peso descendente
    materias.sort(key=lambda x: x["peso_pct"], reverse=True)

    return {
        "total_questoes": total_questoes,
        "fonte_peso": "edital" if usar_edital else "questoes",
        "edital_nome": edital_nome or (edital_materias[0]["materia"] if False else ""),
        "total_topicos_edital": total_topicos_edital,
        "materias": materias,
    }


@router.get("/api/heatmap-erros")
def heatmap_erros(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("""
        SELECT q.materia, q.topico, COUNT(*) as total,
               SUM(CASE WHEN qr.acertou=0 THEN 1 ELSE 0 END) as erros
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia, q.topico ORDER BY q.materia, erros DESC
    """, (user_id,)).fetchall()

    materias_map = {}
    for r in rows:
        mat, topico = r[0], r[1] or "(sem tópico)"
        total, erros = r[2], r[3] or 0
        pct_erro = round((erros / total * 100) if total > 0 else 0, 1)
        intensidade = 0 if pct_erro == 0 else 1 if pct_erro <= 20 else 2 if pct_erro <= 40 else 3 if pct_erro <= 60 else 4
        if mat not in materias_map:
            materias_map[mat] = {"materia": mat, "total_erros": 0, "total_questoes": 0, "topicos": []}
        materias_map[mat]["total_erros"] += erros
        materias_map[mat]["total_questoes"] += total
        materias_map[mat]["topicos"].append({"topico": topico, "erros": erros, "total": total, "pct_erro": pct_erro, "intensidade": intensidade})

    materias = []
    for mat_data in materias_map.values():
        total_q, total_e = mat_data["total_questoes"], mat_data["total_erros"]
        mat_data["pct_erro"] = round((total_e / total_q * 100) if total_q > 0 else 0, 1)
        materias.append(mat_data)
    materias.sort(key=lambda x: x["pct_erro"], reverse=True)
    return {"materias": materias}


@router.get("/api/evolucao")
def evolucao_semanal(semanas: int = 12, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    inicio = (date.today() - timedelta(weeks=semanas)).isoformat()
    rows = conn.execute("""
        SELECT qr.data, q.materia, qr.acertou
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.data >= ? AND qr.user_id = ? ORDER BY qr.data
    """, (inicio, user_id)).fetchall()

    semanas_map = {}
    for r in rows:
        try:
            d = date.fromisoformat(r[0])
        except (ValueError, TypeError):
            continue
        iso = d.isocalendar()
        semana_key = f"{iso[0]}-W{iso[1]:02d}"
        inicio_semana = (d - timedelta(days=d.weekday())).isoformat()
        if semana_key not in semanas_map:
            semanas_map[semana_key] = {"semana": semana_key, "inicio": inicio_semana, "materias": {}, "geral": {"questoes": 0, "acertos": 0}}
        mat, acertou = r[1], r[2]
        if mat not in semanas_map[semana_key]["materias"]:
            semanas_map[semana_key]["materias"][mat] = {"questoes": 0, "acertos": 0}
        semanas_map[semana_key]["materias"][mat]["questoes"] += 1
        semanas_map[semana_key]["materias"][mat]["acertos"] += (acertou or 0)
        semanas_map[semana_key]["geral"]["questoes"] += 1
        semanas_map[semana_key]["geral"]["acertos"] += (acertou or 0)

    streaks_rows = conn.execute("""
        SELECT data, horas_estudadas, questoes_resolvidas, flashcards_revisados
        FROM streaks WHERE data >= ? AND user_id = ? ORDER BY data
    """, (inicio, user_id)).fetchall()
    for sr in streaks_rows:
        try:
            d = date.fromisoformat(sr[0])
        except (ValueError, TypeError):
            continue
        iso = d.isocalendar()
        semana_key = f"{iso[0]}-W{iso[1]:02d}"
        inicio_semana = (d - timedelta(days=d.weekday())).isoformat()
        if semana_key not in semanas_map:
            semanas_map[semana_key] = {"semana": semana_key, "inicio": inicio_semana, "materias": {}, "geral": {"questoes": 0, "acertos": 0}}
        if "horas" not in semanas_map[semana_key]["geral"]:
            semanas_map[semana_key]["geral"]["horas"] = 0
            semanas_map[semana_key]["geral"]["flashcards"] = 0
        semanas_map[semana_key]["geral"]["horas"] += (sr[1] or 0)
        semanas_map[semana_key]["geral"]["flashcards"] += (sr[3] or 0)

    evolucao = []
    for key in sorted(semanas_map.keys()):
        sem = semanas_map[key]
        materias_list = []
        for mat, dados in sem.get("materias", {}).items():
            pct = round((dados["acertos"] / dados["questoes"] * 100) if dados["questoes"] > 0 else 0, 1)
            materias_list.append({"materia": mat, "questoes": dados["questoes"], "acertos": dados["acertos"], "pct": pct})
        geral = sem["geral"]
        geral["pct"] = round((geral["acertos"] / geral["questoes"] * 100) if geral["questoes"] > 0 else 0, 1)
        evolucao.append({"semana": sem["semana"], "inicio": sem.get("inicio", ""), "materias": materias_list, "geral": geral})

    tendencia = []
    if len(evolucao) >= 2:
        todas_materias = set()
        for sem in evolucao:
            for m in sem["materias"]:
                todas_materias.add(m["materia"])
        ultimas_4 = evolucao[-4:] if len(evolucao) >= 4 else evolucao
        anteriores = evolucao[:-4] if len(evolucao) > 4 else []
        for mat in sorted(todas_materias):
            pcts_recentes = [m["pct"] for sem in ultimas_4 for m in sem["materias"] if m["materia"] == mat]
            media_recente = sum(pcts_recentes) / len(pcts_recentes) if pcts_recentes else 0
            pcts_anteriores = [m["pct"] for sem in anteriores for m in sem["materias"] if m["materia"] == mat]
            media_anterior = sum(pcts_anteriores) / len(pcts_anteriores) if pcts_anteriores else media_recente
            delta = round(media_recente - media_anterior, 1)
            tendencia_str = "melhorando" if delta > 3 else "piorando" if delta < -3 else "estavel"
            tendencia.append({"materia": mat, "tendencia": tendencia_str, "delta": delta})

    return {"semanas": semanas, "evolucao": evolucao, "tendencia": tendencia}


@router.get("/api/analytics/velocidade")
def analytics_velocidade(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("""
        SELECT q.materia, AVG(qr.tempo_segundos) as media_seg, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.tempo_segundos > 0 AND qr.user_id = ? GROUP BY q.materia ORDER BY media_seg DESC
    """, (user_id,)).fetchall()
    geral = conn.execute("SELECT AVG(tempo_segundos) FROM questoes_respostas WHERE tempo_segundos > 0 AND user_id = ?", (user_id,)).fetchone()[0]
    return {
        "media_geral_seg": round(geral, 1) if geral else 0,
        "por_materia": [{"materia": r["materia"], "media_seg": round(r["media_seg"], 1), "total": r["total"],
                         "pct_acerto": round(r["acertos"] / r["total"] * 100, 1) if r["total"] > 0 else 0} for r in rows]
    }


@router.get("/api/analytics/consistencia")
def analytics_consistencia(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    inicio = (date.today() - timedelta(days=27)).isoformat()
    sessoes = conn.execute(
        "SELECT data, SUM(horas) as total FROM sessoes_estudo WHERE data >= ? AND user_id = ? GROUP BY data", (inicio, user_id)
    ).fetchall()
    dias_estudados = len(sessoes)
    horas_total = sum(s["total"] for s in sessoes)
    media_horas_dia = round(horas_total / dias_estudados, 1) if dias_estudados > 0 else 0

    dist_semana = [0] * 7
    for s in sessoes:
        d = date.fromisoformat(s["data"])
        dist_semana[d.weekday()] += s["total"]

    streaks = conn.execute("SELECT data FROM streaks WHERE user_id = ? ORDER BY data DESC", (user_id,)).fetchall()
    streak_atual = 0
    hoje = date.today()
    for s in streaks:
        d = date.fromisoformat(s["data"])
        if d == hoje - timedelta(days=streak_atual):
            streak_atual += 1
        else:
            break

    return {
        "dias_estudados": dias_estudados, "dias_totais": 28,
        "pct_consistencia": round(dias_estudados / 28 * 100, 1),
        "horas_total": round(horas_total, 1), "media_horas_dia": media_horas_dia,
        "streak_atual": streak_atual, "distribuicao_semana": dist_semana,
        "dias_semana_nomes": ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    }


@router.get("/api/analytics/metas-realizado")
def analytics_metas_realizado(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cfg = conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    meta_horas = cfg["meta_horas"] if cfg else 3
    meta_questoes = cfg["meta_questoes"] if cfg else 30
    semanas = []
    for i in range(4):
        fim = date.today() - timedelta(days=i * 7)
        inicio = fim - timedelta(days=6)
        horas = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data BETWEEN ? AND ? AND user_id = ?",
            (inicio.isoformat(), fim.isoformat(), user_id)).fetchone()[0]
        questoes = conn.execute(
            "SELECT COUNT(*) FROM questoes_respostas WHERE data BETWEEN ? AND ? AND user_id = ?",
            (inicio.isoformat(), fim.isoformat(), user_id)).fetchone()[0]
        semanas.append({
            "semana": f"{inicio.strftime('%d/%m')} - {fim.strftime('%d/%m')}",
            "horas_meta": round(meta_horas * 7, 1), "horas_real": round(horas, 1),
            "questoes_meta": meta_questoes * 7, "questoes_real": questoes,
            "pct_horas": round(horas / (meta_horas * 7) * 100, 1) if meta_horas > 0 else 0,
            "pct_questoes": round(questoes / (meta_questoes * 7) * 100, 1) if meta_questoes > 0 else 0,
        })
    semanas.reverse()
    return {"semanas": semanas}


@router.get("/api/analytics/ranking-materias")
def analytics_ranking_materias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos, AVG(qr.tempo_segundos) as media_tempo
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia HAVING total >= 3
        ORDER BY (CAST(acertos AS REAL) / total) ASC
    """, (user_id,)).fetchall()
    ranking = []
    for r in rows:
        pct = round(r["acertos"] / r["total"] * 100, 1)
        if pct >= 80:
            status, acao = "forte", "Manter revisão espaçada"
        elif pct >= 60:
            status, acao = "medio", "Aumentar questões e revisar erros"
        else:
            status, acao = "fraco", "Priorizar estudo teórico + questões comentadas"
        ranking.append({"materia": r["materia"], "total": r["total"], "pct_acerto": pct,
                        "media_tempo_seg": round(r["media_tempo"], 1) if r["media_tempo"] else 0,
                        "status": status, "acao": acao})
    return {"ranking": ranking, "total_materias": len(ranking),
            "fortes": len([r for r in ranking if r["status"] == "forte"]),
            "medias": len([r for r in ranking if r["status"] == "medio"]),
            "fracas": len([r for r in ranking if r["status"] == "fraco"])}


@router.get("/api/analytics/raio-x")
def raio_x(banca: str = "", materia: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """
    Raio-X: Análise de frequência de tópicos por banca.
    Shows which topics are most tested by specific bancas.
    """
    # Build query with optional filters
    where_clauses = ["qr.user_id = ?"]
    params = [user_id]

    if banca:
        where_clauses.append("q.banca = ?")
        params.append(banca)
    if materia:
        where_clauses.append("q.materia = ?")
        params.append(materia)

    where = " AND ".join(where_clauses)

    # Topic frequency: how many questions per topic
    topic_freq = conn.execute(f"""
        SELECT q.materia, q.topico, q.banca,
               COUNT(*) as total_questoes,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE {where}
        GROUP BY q.materia, q.topico
        ORDER BY total_questoes DESC
    """, params).fetchall()

    # Overall stats per materia
    materia_stats = conn.execute(f"""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto,
               COUNT(DISTINCT q.topico) as topicos_cobrados
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE {where}
        GROUP BY q.materia
        ORDER BY total DESC
    """, params).fetchall()

    # Available bancas for filter
    bancas = conn.execute(
        "SELECT DISTINCT banca FROM questoes WHERE banca != '' AND user_id = ? ORDER BY banca", (user_id,)
    ).fetchall()

    # Available materias for filter
    materias = conn.execute(
        "SELECT DISTINCT materia FROM questoes WHERE user_id = ? ORDER BY materia", (user_id,)
    ).fetchall()

    return {
        "topicos": [dict(r) for r in topic_freq],
        "materias": [dict(r) for r in materia_stats],
        "filtros": {
            "bancas": [r[0] for r in bancas],
            "materias": [r[0] for r in materias]
        },
        "banca_selecionada": banca,
        "materia_selecionada": materia
    }


@router.get("/api/analytics/raio-x/prioridades")
def raio_x_prioridades(banca: str = "", edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """
    Combines Raio-X frequency data with edital topics to suggest study priorities.
    Topics that are frequently tested but have low mastery get highest priority.
    """
    # Get question frequency per topic from this banca
    freq_query = "SELECT q.materia, q.topico, COUNT(*) as freq FROM questoes q WHERE q.user_id = ?"
    freq_params = [user_id]
    if banca:
        freq_query += " AND q.banca = ?"
        freq_params.append(banca)
    freq_query += " GROUP BY q.materia, q.topico"

    freq_data = conn.execute(freq_query, freq_params).fetchall()
    freq_map = {(r[0], r[1]): r[2] for r in freq_data}

    # Get edital topics with mastery
    edital_where = "user_id = ? AND arquivado = 0"
    edital_params = [user_id]
    if edital_nome:
        edital_where += " AND edital_nome = ?"
        edital_params.append(edital_nome)
    if cargo:
        edital_where += " AND cargo = ?"
        edital_params.append(cargo)

    topics = conn.execute(f"""
        SELECT id, materia, topico, status, mastery_level
        FROM edital WHERE {edital_where}
        ORDER BY materia, topico
    """, edital_params).fetchall()

    # Calculate priority score for each topic
    priorities = []
    for t in topics:
        mastery = t["mastery_level"] or 0
        # Find frequency match (fuzzy: check if edital topic appears in question topics)
        freq = 0
        for (mat, top), count in freq_map.items():
            if mat == t["materia"] or (t["topico"] and t["topico"].lower() in top.lower()):
                freq += count

        # Priority formula: high frequency + low mastery = high priority
        # Normalize: freq_score (0-100), mastery_gap (0-100)
        max_freq = max((v for v in freq_map.values()), default=1)
        freq_score = (freq / max_freq) * 100 if max_freq > 0 else 0
        mastery_gap = 100 - mastery

        priority_score = round(freq_score * 0.6 + mastery_gap * 0.4, 1)

        priorities.append({
            "id": t["id"],
            "materia": t["materia"],
            "topico": t["topico"],
            "status": t["status"],
            "mastery_level": mastery,
            "frequencia": freq,
            "priority_score": priority_score,
            "recomendacao": "URGENTE" if priority_score >= 70 else "IMPORTANTE" if priority_score >= 40 else "NORMAL"
        })

    # Sort by priority (highest first)
    priorities.sort(key=lambda x: x["priority_score"], reverse=True)

    return {
        "prioridades": priorities[:50],  # Top 50
        "total_topicos": len(priorities),
        "banca": banca,
        "edital_nome": edital_nome
    }


@router.get("/api/analytics/raio-x/bancas")
def raio_x_bancas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Performance comparison across different bancas."""
    stats = conn.execute("""
        SELECT q.banca,
               COUNT(*) as total_questoes,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto,
               COUNT(DISTINCT q.materia) as materias_praticadas
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND q.banca != ''
        GROUP BY q.banca
        ORDER BY total_questoes DESC
    """, (user_id,)).fetchall()

    return [dict(r) for r in stats]


# ============================================================
# WEEKLY WRAP — Study insights with comparative analysis
# ============================================================

@router.get("/api/insights/weekly-wrap", summary="Weekly Study Wrap",
            description="Comprehensive weekly summary with comparative insights, achievements, and recommendations.")
def weekly_wrap(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera um resumo semanal inteligente com comparações e conquistas."""
    hoje = date.today()
    inicio_semana = (hoje - timedelta(days=hoje.weekday())).isoformat()
    inicio_semana_ant = (hoje - timedelta(days=hoje.weekday() + 7)).isoformat()
    fim_semana_ant = (hoje - timedelta(days=hoje.weekday() + 1)).isoformat()

    # --- Current week metrics ---
    horas_semana = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND user_id = ?",
        (inicio_semana, user_id)
    ).fetchone()[0]

    questoes_semana = conn.execute(
        "SELECT COUNT(*) as total, COALESCE(SUM(acertou), 0) as acertos FROM questoes_respostas WHERE data >= ? AND user_id = ?",
        (inicio_semana, user_id)
    ).fetchone()

    try:
        flashcards_semana = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao > ? AND user_id = ?",
            (inicio_semana, user_id)
        ).fetchone()[0]
    except Exception:
        flashcards_semana = 0

    dias_ativos = conn.execute(
        "SELECT COUNT(DISTINCT data) FROM streaks WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0) AND user_id = ?",
        (inicio_semana, user_id)
    ).fetchone()[0]

    # --- Previous week metrics (for comparison) ---
    horas_ant = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND data <= ? AND user_id = ?",
        (inicio_semana_ant, fim_semana_ant, user_id)
    ).fetchone()[0]

    questoes_ant = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE data >= ? AND data <= ? AND user_id = ?",
        (inicio_semana_ant, fim_semana_ant, user_id)
    ).fetchone()[0]

    # --- Streak info ---
    streak_data = calculate_streak(conn, user_id)
    streak = streak_data["streak_atual"]

    # --- Best/worst subjects this week ---
    materias_semana = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.data >= ? AND qr.user_id = ?
        GROUP BY q.materia HAVING total >= 3
        ORDER BY pct ASC
    """, (inicio_semana, user_id)).fetchall()

    melhor_materia = None
    pior_materia = None
    if materias_semana:
        pior = materias_semana[0]
        pior_materia = {"materia": pior["materia"], "pct": pior["pct"], "total": pior["total"]}
        melhor = materias_semana[-1]
        melhor_materia = {"materia": melhor["materia"], "pct": melhor["pct"], "total": melhor["total"]}

    # --- Achievements (badges earned this week) ---
    conquistas = []
    if streak >= 7:
        conquistas.append({"icon": "🔥", "label": f"Streak de {streak} dias"})
    if questoes_semana[0] >= 100:
        conquistas.append({"icon": "💯", "label": f"{questoes_semana[0]} questões resolvidas"})
    elif questoes_semana[0] >= 50:
        conquistas.append({"icon": "📝", "label": f"{questoes_semana[0]} questões resolvidas"})
    if horas_semana >= 20:
        conquistas.append({"icon": "🏆", "label": f"{round(horas_semana, 1)}h estudadas"})
    elif horas_semana >= 10:
        conquistas.append({"icon": "⏰", "label": f"{round(horas_semana, 1)}h estudadas"})
    if dias_ativos >= 7:
        conquistas.append({"icon": "✨", "label": "Semana perfeita!"})
    if flashcards_semana >= 50:
        conquistas.append({"icon": "🧠", "label": f"{flashcards_semana} flashcards revisados"})
    if questoes_semana[0] > 0 and questoes_semana[1] / questoes_semana[0] >= 0.8:
        conquistas.append({"icon": "🎯", "label": f"{round(questoes_semana[1] / questoes_semana[0] * 100)}% de acerto"})

    # --- Comparative deltas ---
    delta_horas = round(horas_semana - horas_ant, 1) if horas_ant else None
    delta_questoes = (questoes_semana[0] - questoes_ant) if questoes_ant else None

    # --- Pending reviews ---
    pending_flashcards = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
        (today_str(), user_id)
    ).fetchone()[0]

    pending_topicos = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE proxima_revisao != '' AND proxima_revisao <= ? AND user_id = ?",
        (today_str(), user_id)
    ).fetchone()[0]

    return {
        "periodo": f"{inicio_semana} a {hoje.isoformat()}",
        "resumo": {
            "horas_estudadas": round(horas_semana, 1),
            "questoes_resolvidas": questoes_semana[0],
            "questoes_acertadas": questoes_semana[1],
            "pct_acerto": round(questoes_semana[1] / questoes_semana[0] * 100, 1) if questoes_semana[0] else 0,
            "flashcards_revisados": flashcards_semana,
            "dias_ativos": dias_ativos,
            "streak_atual": streak,
        },
        "comparativo": {
            "delta_horas": delta_horas,
            "delta_questoes": delta_questoes,
            "tendencia_horas": "up" if delta_horas and delta_horas > 0 else "down" if delta_horas and delta_horas < 0 else "stable",
            "tendencia_questoes": "up" if delta_questoes and delta_questoes > 0 else "down" if delta_questoes and delta_questoes < 0 else "stable",
        },
        "destaques": {
            "melhor_materia": melhor_materia,
            "pior_materia": pior_materia,
        },
        "conquistas": conquistas,
        "pendencias": {
            "flashcards_pendentes": pending_flashcards,
            "topicos_revisao": pending_topicos,
        },
    }


# ============================================================
# ROI POR MATÉRIA — Retorno sobre investimento de estudo
# ============================================================

@router.get("/api/analytics/roi-materias", summary="ROI por matéria",
            description="Calcula o retorno sobre investimento de estudo por matéria: (peso_banca * gap) / (horas + 1). Ordena por ROI descendente.")
def roi_materias(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """ROI = (peso_banca * gap) / (horas_investidas + 1). Maior ROI = maior ganho potencial por hora extra."""

    # 1. Obter peso de cada matéria na banca (% de questões)
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes WHERE user_id = ?", (user_id,)).fetchone()[0]
    questoes_por_mat = conn.execute(
        "SELECT materia, COUNT(*) as qtd FROM questoes WHERE user_id = ? GROUP BY materia",
        (user_id,)
    ).fetchall()
    peso_map = {}
    for r in questoes_por_mat:
        peso_map[r["materia"]] = round(r["qtd"] / total_questoes * 100, 1) if total_questoes > 0 else 0

    # 2. Obter % de acerto por matéria
    acertos_por_mat = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
    """, (user_id,)).fetchall()
    acerto_map = {r["materia"]: round((r["acertos"] or 0) / r["total"] * 100, 1) if r["total"] > 0 else 0 for r in acertos_por_mat}

    # 3. Obter horas estudadas por matéria
    horas_por_mat = conn.execute(
        "SELECT materia, COALESCE(SUM(horas), 0) as total FROM sessoes_estudo WHERE user_id = ? GROUP BY materia",
        (user_id,)
    ).fetchall()
    horas_map = {r["materia"]: round(r["total"], 1) for r in horas_por_mat}

    # 4. Obter todas as matérias do edital (se houver filtro)
    edital_query = "SELECT DISTINCT materia FROM edital WHERE user_id = ? AND arquivado = 0"
    edital_params = [user_id]
    if edital_nome:
        edital_query += " AND edital_nome = ?"
        edital_params.append(edital_nome)
    if cargo:
        edital_query += " AND cargo = ?"
        edital_params.append(cargo)
    materias_edital = [r[0] for r in conn.execute(edital_query, edital_params).fetchall()]

    # Unir matérias do edital + matérias com questões
    todas_materias = set(materias_edital) | set(peso_map.keys())

    # 5. Calcular ROI para cada matéria
    resultados = []
    for materia in todas_materias:
        peso_banca = peso_map.get(materia, 0)
        pct_atual = acerto_map.get(materia, 0)
        gap = 100 - pct_atual
        horas_investidas = horas_map.get(materia, 0)
        roi = round((peso_banca * gap) / (horas_investidas + 1), 2)

        resultados.append({
            "materia": materia,
            "peso_banca": peso_banca,
            "pct_atual": pct_atual,
            "gap": round(gap, 1),
            "horas_investidas": horas_investidas,
            "roi": roi,
            "classificacao": "",  # preenchido abaixo
        })

    # 6. Ordenar por ROI desc
    resultados.sort(key=lambda x: -x["roi"])

    # 7. Classificar: top 30% = Alto ROI, 30-70% = Médio, bottom 30% = Baixo
    n = len(resultados)
    if n > 0:
        top_30 = max(1, int(n * 0.3))
        bottom_30_start = n - max(1, int(n * 0.3))
        for i, r in enumerate(resultados):
            if i < top_30:
                r["classificacao"] = "Alto ROI"
            elif i >= bottom_30_start:
                r["classificacao"] = "Baixo"
            else:
                r["classificacao"] = "Médio"

    return {
        "materias": resultados,
        "total_materias": n,
        "resumo": {
            "alto_roi": len([r for r in resultados if r["classificacao"] == "Alto ROI"]),
            "medio": len([r for r in resultados if r["classificacao"] == "Médio"]),
            "baixo": len([r for r in resultados if r["classificacao"] == "Baixo"]),
        }
    }

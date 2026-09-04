"""Router de Analytics e Relatórios Avançados."""
import json
import re
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from database import get_db_session
from deps import get_user_id
from logger import log
from services import get_acertos_por_materia, get_horas_estudadas
from utils import calculate_streak, sql_paginate, today_str

router = APIRouter(prefix="", tags=["Analytics"])


@router.get("/api/relatorio-semanal", summary="Relatório semanal")
def relatorio_semanal(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    inicio_semana = (date.today() - timedelta(days=date.today().weekday())).isoformat()

    horas = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND user_id = ?", (inicio_semana, user_id)
    ).fetchone()[0]

    questoes = conn.execute(
        "SELECT COUNT(*) as total, SUM(acertou) as acertos FROM questoes_respostas WHERE data >= ? AND user_id = ?",
        (inicio_semana, user_id)
    ).fetchone()

    materia_fraca = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.data >= ? AND qr.user_id = ?
        GROUP BY q.materia HAVING total >= 3
        ORDER BY pct ASC LIMIT 3
    """, (inicio_semana, user_id)).fetchall()

    dias = conn.execute("""
        SELECT COUNT(DISTINCT data) FROM streaks
        WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0) AND user_id = ?
    """, (inicio_semana, user_id)).fetchone()[0]

    return {
        "periodo": f"{inicio_semana} a {today_str()}",
        "total_horas": round(horas, 1),
        "questoes_total": questoes[0] or 0,
        "questoes_acertos": questoes[1] or 0,
        "questoes_percentual": round((questoes[1] / questoes[0] * 100) if questoes[0] else 0, 1),
        "materias_fracas": [dict(r) for r in materia_fraca],
        "dias_estudados": dias,
        "sugestao_foco": [r["materia"] for r in materia_fraca] if materia_fraca else ["Resolver mais questões para obter análise"]
    }


@router.get("/api/resumo-diario")
def resumo_diario(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    sessoes = conn.execute("SELECT materia, SUM(horas) FROM sessoes_estudo WHERE data = ? AND user_id = ? GROUP BY materia", (today_str(), user_id)).fetchall()
    q_hoje = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id=qr.questao_id
        WHERE qr.data = ? AND qr.user_id = ? GROUP BY q.materia
    """, (today_str(), user_id)).fetchall()
    menos_estudada = conn.execute("""
        SELECT materia, SUM(horas_estudadas) as h FROM edital
        WHERE status != 'Concluído' AND user_id = ? GROUP BY materia ORDER BY h ASC LIMIT 3
    """, (user_id,)).fetchall()

    # Fonte de verdade para "questões de hoje": a tabela real questoes_respostas
    # (soma de q_hoje), não o contador streaks.questoes_resolvidas — que também é
    # incrementado por revisões do caderno de erros e divergia do dashboard.
    questoes_hoje_total = sum(r[1] for r in q_hoje)

    return {
        "data": today_str(),
        "horas": hoje["horas_estudadas"] if hoje else 0,
        "questoes": questoes_hoje_total,
        "flashcards": hoje["flashcards_revisados"] if hoje else 0,
        "sessoes": [
            {"materia": r[0], "horas": round(r[1], 2), "minutos": round((r[1] or 0) * 60)}
            for r in sessoes
        ],
        "questoes_detalhes": [{"materia": r[0], "total": r[1], "acertos": r[2] or 0} for r in q_hoje],
        "sugestao_amanha": [r[0] for r in menos_estudada],
        "mensagem": "Continue assim! Amanhã foque nas matérias sugeridas." if hoje else "Você não estudou hoje. Começar é o mais difícil!"
    }


@router.get("/api/pratica-deliberada")
def pratica_deliberada(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    materias = get_acertos_por_materia(conn, user_id)
    materias_sorted = sorted(materias, key=lambda x: x["pct"])

    nao_estudadas = conn.execute("""
        SELECT DISTINCT materia FROM questoes
        WHERE user_id = ? AND materia NOT IN (
            SELECT DISTINCT q.materia FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ?
        )
    """, (user_id, user_id)).fetchall()

    sugestoes = []
    for m in materias_sorted:
        if m["pct"] < 70:
            sugestoes.append({
                "materia": m["materia"], "total_questoes": m["total"], "percentual": m["pct"],
                "prioridade": "ALTA" if m["pct"] < 50 else "MÉDIA"
            })

    return {
        "materias_para_focar": sugestoes,
        "materias_nao_estudadas": [r[0] for r in nao_estudadas],
        "recomendacao": "Foque nas matérias com menor percentual de acerto. Resolva pelo menos 10 questões de cada antes de avançar."
    }


@router.get("/api/radar")
def get_radar(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = """
        SELECT materia, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos,
               SUM(horas_estudadas) as horas
        FROM edital WHERE user_id = ?
    """
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " GROUP BY materia ORDER BY materia"
    materias_edital = conn.execute(query, params).fetchall()

    questoes_por_mat = get_acertos_por_materia(conn, user_id)
    q_map = {r["materia"]: {"total": r["total"], "acertos": r["acertos"]} for r in questoes_por_mat}

    radar_data = []
    for m in materias_edital:
        materia, total, concluidos, horas = m[0], m[1], m[2], m[3] or 0
        pct_edital = (concluidos / total * 100) if total > 0 else 0
        q_data = q_map.get(materia, {"total": 0, "acertos": 0})
        pct_questoes = (q_data["acertos"] / q_data["total"] * 100) if q_data["total"] > 0 else 0
        score = (pct_edital + pct_questoes) / 2 if q_data["total"] > 0 else pct_edital

        radar_data.append({
            "materia": materia, "score": round(score, 1),
            "pct_edital": round(pct_edital, 1), "pct_questoes": round(pct_questoes, 1),
            "horas": round(horas, 1), "topicos_total": total, "topicos_concluidos": concluidos
        })
    return radar_data


@router.get("/api/heatmap")
def get_heatmap(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    inicio = (date.today() - timedelta(days=365)).isoformat()
    rows = conn.execute("""
        SELECT data, horas_estudadas, questoes_resolvidas, flashcards_revisados
        FROM streaks WHERE data >= ? AND user_id = ? ORDER BY data
    """, (inicio, user_id)).fetchall()

    result = []
    for r in rows:
        horas, questoes, flashcards = r[1] or 0, r[2] or 0, r[3] or 0
        score = (horas / 0.5) + (questoes / 10) + (flashcards / 5)
        intensidade = min(4, max(1, int(score))) if score > 0 else 0
        result.append({"data": r[0], "horas": horas, "questoes": questoes,
                       "flashcards": flashcards, "intensidade": intensidade})
    return result


@router.get("/api/projecao-nota")
def projecao_nota(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT DISTINCT materia FROM edital WHERE user_id = ?"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    materias = [r[0] for r in conn.execute(query, params).fetchall()]

    total_pontos = 0
    total_possiveis = 0
    detalhes = []
    for mat in materias:
        q = conn.execute("""
            SELECT COUNT(*) as total, SUM(acertou) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id=qr.questao_id WHERE q.materia = ? AND qr.user_id = ?
        """, (mat, user_id)).fetchone()
        total_q, acertos = q[0] or 0, q[1] or 0
        pct = (acertos / total_q * 100) if total_q > 0 else 50
        total_pontos += pct
        total_possiveis += 100
        detalhes.append({"materia": mat, "pct_acerto": round(pct, 1), "questoes": total_q})

    nota_projetada = (total_pontos / total_possiveis * 100) if total_possiveis > 0 else 0
    return {
        "nota_projetada": round(nota_projetada, 1), "nota_corte_estimada": 60.0,
        "aprovado_estimado": nota_projetada >= 60,
        "materias": sorted(detalhes, key=lambda x: x['pct_acerto']),
        "total_materias": len(materias)
    }


@router.get("/api/previsao-aprovacao")
def previsao_aprovacao(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query_base = "SELECT COUNT(*) FROM edital WHERE user_id = ?"
    query_done = "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?"
    params = [user_id]
    if edital_nome:
        query_base += " AND edital_nome = ?"
        query_done += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query_base += " AND cargo = ?"
        query_done += " AND cargo = ?"
        params.append(cargo)

    total_topicos = conn.execute(query_base, params).fetchone()[0]
    topicos_concluidos = conn.execute(query_done, params).fetchone()[0]
    q_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    q_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    horas_total = get_horas_estudadas(conn, user_id)

    pct_edital = (topicos_concluidos / total_topicos * 100) if total_topicos > 0 else 0
    pct_questoes = (q_acertos / q_total * 100) if q_total > 0 else 0
    fator_horas = min(100, horas_total * 2)
    score = (pct_edital * 0.4) + (pct_questoes * 0.5) + (fator_horas * 0.1)

    if score >= 80:
        nivel, emoji = "Excelente", "🏆"
    elif score >= 60:
        nivel, emoji = "Bom", "✅"
    elif score >= 40:
        nivel, emoji = "Regular", "⚠️"
    elif score >= 20:
        nivel, emoji = "Iniciante", "📖"
    else:
        nivel, emoji = "Começando", "🌱"

    return {
        "score": round(score, 1), "nivel": nivel, "emoji": emoji,
        "detalhes": {
            "edital_pct": round(pct_edital, 1), "questoes_pct": round(pct_questoes, 1),
            "horas_total": round(horas_total, 1), "topicos_concluidos": topicos_concluidos,
            "topicos_total": total_topicos, "questoes_total": q_total, "questoes_acertos": q_acertos
        }
    }


@router.get("/api/previsao-data-aprovacao")
def previsao_data_aprovacao(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    try:
        query = "SELECT COUNT(*) FROM edital WHERE status != 'Concluído' AND user_id = ?"
        params = [user_id]
        if edital_nome:
            query += " AND edital_nome = ?"
            params.append(edital_nome)
        if cargo:
            query += " AND cargo = ?"
            params.append(cargo)
        restantes = int(conn.execute(query, params).fetchone()[0] or 0)

        quatro_semanas = (date.today() - timedelta(days=28)).isoformat()
        total_horas_4sem = float(conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND user_id = ?", (quatro_semanas, user_id)
        ).fetchone()[0] or 0)
    except Exception:
        return {"semanas_restantes": None, "data_prevista": None,
                "message": "Erro ao calcular. Estude mais para gerar previsão.", "restantes": 0}

    horas_por_semana = total_horas_4sem / 4 if total_horas_4sem > 0 else 0
    topicos_por_semana = horas_por_semana * 2

    if topicos_por_semana <= 0 or restantes <= 0:
        return {"semanas_restantes": None, "data_prevista": None,
                "message": "Estude mais para gerar previsão.", "restantes": restantes}

    semanas = min(restantes / topicos_por_semana, 520)
    data_prevista = (date.today() + timedelta(weeks=int(semanas))).isoformat()

    return {
        "semanas_restantes": round(semanas, 1), "data_prevista": data_prevista,
        "restantes": restantes, "ritmo_semanal": round(topicos_por_semana, 1),
        "horas_semana": round(horas_por_semana, 1)
    }


@router.get("/api/analise-erros")
def analise_padroes_erro(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    erros_por_materia = conn.execute("""
        SELECT q.materia, COUNT(*) as erros,
               (SELECT COUNT(*) FROM questoes_respostas qr2 JOIN questoes q2 ON q2.id=qr2.questao_id WHERE q2.materia=q.materia AND qr2.user_id=?) as total
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0 AND qr.user_id = ? GROUP BY q.materia ORDER BY erros DESC
    """, (user_id, user_id)).fetchall()

    erros_por_topico = conn.execute("""
        SELECT q.materia, q.enunciado, COUNT(*) as vezes_errado
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0 AND qr.user_id = ? GROUP BY qr.questao_id ORDER BY vezes_errado DESC LIMIT 10
    """, (user_id,)).fetchall()

    sugestoes = []
    for r in erros_por_materia:
        pct_erro = (r[1] / r[2] * 100) if r[2] > 0 else 0
        if pct_erro > 40:
            sugestoes.append(f"Revise {r[0]} — {pct_erro:.0f}% de erro ({r[1]} erros em {r[2]} questões)")

    return {
        "erros_por_materia": [{"materia": r[0], "erros": r[1], "total": r[2],
                               "pct_erro": round(r[1] / r[2] * 100, 1) if r[2] > 0 else 0} for r in erros_por_materia],
        "questoes_mais_erradas": [{"materia": r[0], "enunciado": r[1][:100], "vezes": r[2]} for r in erros_por_topico],
        "sugestoes": sugestoes
    }


@router.get("/api/comparativo")
def comparativo_cargos(edital1: str = "", cargo1: str = "", edital2: str = "", cargo2: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    mat1 = set(r[0] for r in conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE edital_nome = ? AND cargo = ? AND user_id = ?", (edital1, cargo1, user_id)).fetchall())
    mat2 = set(r[0] for r in conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE edital_nome = ? AND cargo = ? AND user_id = ?", (edital2, cargo2, user_id)).fetchall())
    comuns = sorted(mat1 & mat2)
    apenas1 = sorted(mat1 - mat2)
    apenas2 = sorted(mat2 - mat1)
    return {"cargo1": f"{edital1} - {cargo1}", "cargo2": f"{edital2} - {cargo2}",
            "comuns": comuns, "apenas_cargo1": apenas1, "apenas_cargo2": apenas2,
            "total_comuns": len(comuns), "total_apenas1": len(apenas1), "total_apenas2": len(apenas2)}


@router.get("/api/comparador-progresso")
def comparador_progresso(apenas_ciclo: bool = True, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    # If apenas_ciclo, filter by subjects in the active ciclo
    ciclo_filter = ""
    if apenas_ciclo:
        ciclo_materias = conn.execute(
            "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
        ).fetchall()
        if ciclo_materias:
            materias_list = [r[0] for r in ciclo_materias]
            placeholders = ",".join("?" * len(materias_list))
            ciclo_filter = f" AND materia IN ({placeholders})"
        else:
            ciclo_filter = ""
            materias_list = []

    query = f"""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status='Concluído' THEN 1 ELSE 0 END) as done,
               SUM(horas_estudadas) as horas
        FROM edital WHERE user_id = ?{ciclo_filter} GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """
    params = [user_id] + (materias_list if apenas_ciclo and ciclo_filter else [])
    rows = conn.execute(query, params).fetchall()
    return [{"edital": r[0], "cargo": r[1], "total": r[2], "concluidos": r[3] or 0,
             "pct": round((r[3] or 0) / r[2] * 100, 1) if r[2] > 0 else 0,
             "horas": round(r[4] or 0, 1)} for r in rows]


@router.get("/api/planejador-aprovacao")
def planejador_aprovacao(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    # Auto-detectar edital do ciclo ativo
    if not edital_nome and not cargo:
        try:
            ciclo_edital = conn.execute("""
                SELECT e.edital_nome, COUNT(DISTINCT e.materia) as matches
                FROM edital e
                INNER JOIN ciclo_estudos c ON c.materia = e.materia AND c.user_id = e.user_id
                WHERE c.ativo = 1 AND c.user_id = ? AND e.arquivado = 0
                GROUP BY e.edital_nome ORDER BY matches DESC LIMIT 1
            """, (user_id,)).fetchone()
            if ciclo_edital and ciclo_edital["edital_nome"]:
                edital_nome = ciclo_edital["edital_nome"]
        except Exception:
            pass

    query = "SELECT materia, COUNT(*) as total, SUM(CASE WHEN status='Concluído' THEN 1 ELSE 0 END) as done, SUM(horas_estudadas) as horas FROM edital WHERE user_id = ? AND arquivado = 0"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)

    # Filtrar por matérias do ciclo ativo
    ciclo_materias = conn.execute(
        "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
    ).fetchall()
    if ciclo_materias and not cargo:
        ciclo_mats = [m["materia"] for m in ciclo_materias]
        placeholders = ",".join("?" * len(ciclo_mats))
        query += f" AND materia IN ({placeholders})"
        params.extend(ciclo_mats)

    query += " GROUP BY materia ORDER BY materia"
    materias = conn.execute(query, params).fetchall()

    q_stats = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id WHERE qr.user_id = ? GROUP BY q.materia
    """, (user_id,)).fetchall()
    q_map = {r[0]: {"total": r[1], "acertos": r[2] or 0} for r in q_stats}

    META_EDITAL, META_QUESTOES = 70, 70
    plano = []
    for m in materias:
        materia, total, done, horas = m[0], m[1], m[2] or 0, m[3] or 0
        pct_edital = (done / total * 100) if total > 0 else 0
        q = q_map.get(materia, {"total": 0, "acertos": 0})
        pct_questoes = (q["acertos"] / q["total"] * 100) if q["total"] > 0 else 0
        topicos_faltam = max(0, int(total * META_EDITAL / 100) - done)
        questoes_precisa = max(0, 20 - q["total"])
        status = "ok" if pct_edital >= META_EDITAL and pct_questoes >= META_QUESTOES else "atencao" if pct_edital >= 50 or pct_questoes >= 50 else "critico"
        plano.append({"materia": materia, "pct_edital": round(pct_edital, 1), "pct_questoes": round(pct_questoes, 1),
                      "topicos_faltam": topicos_faltam, "questoes_precisa": questoes_precisa,
                      "horas_estudadas": round(horas, 1), "status": status})
    return {"meta_edital": META_EDITAL, "meta_questoes": META_QUESTOES, "materias": plano}


@router.get("/api/plano-automatico")
def plano_automatico(edital_nome: str = "", cargo: str = "", horas_dia: float = 3.0, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    try:
        prova = conn.execute("""
            SELECT data_prova_objetiva FROM edital_info
            WHERE edital_nome = ? AND cargo = ? AND data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?
        """, (edital_nome, cargo, user_id)).fetchone()
    except Exception:
        prova = None

    query = "SELECT materia, COUNT(*) as total, SUM(CASE WHEN status='Concluído' THEN 1 ELSE 0 END) as done FROM edital WHERE user_id = ?"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " GROUP BY materia ORDER BY materia"
    materias = conn.execute(query, params).fetchall()

    dias_ate_prova = 90
    if prova and prova[0]:
        parts = re.match(r'(\d+)[/\-](\d+)[/\-](\d+)', prova[0])
        if parts:
            if len(parts.group(3)) == 4:
                d = date(int(parts.group(3)), int(parts.group(2)), int(parts.group(1)))
            else:
                d = date(int(parts.group(1)), int(parts.group(2)), int(parts.group(3)))
            dias_ate_prova = max(1, (d - date.today()).days)

    total_horas_disponiveis = dias_ate_prova * horas_dia
    total_topicos_restantes = sum(m[1] - (m[2] or 0) for m in materias)

    plano = []
    for m in materias:
        restantes = m[1] - (m[2] or 0)
        if restantes <= 0:
            continue
        proporcao = restantes / total_topicos_restantes if total_topicos_restantes > 0 else 0
        horas_materia = round(total_horas_disponiveis * proporcao, 1)
        horas_semana = round(horas_materia / (dias_ate_prova / 7), 1)
        plano.append({"materia": m[0], "topicos_restantes": restantes, "horas_total": horas_materia, "horas_semana": horas_semana})

    return {"dias_ate_prova": dias_ate_prova, "horas_dia": horas_dia,
            "total_horas": round(total_horas_disponiveis, 0), "topicos_restantes": total_topicos_restantes,
            "plano": sorted(plano, key=lambda x: -x['topicos_restantes'])}



# ============================================================
# COMPARTILHAMENTO DE PROGRESSO — Card Social
# ============================================================

@router.get("/api/analytics/share-card", summary="Card de compartilhamento de progresso",
            description="Gera dados para card de progresso compartilhável em redes sociais.")
def share_card(
    periodo: str = Query("semana", description="semana, mes, total"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera dados para card de compartilhamento com stats do período."""
    from datetime import timedelta

    hoje = date.today()

    if periodo == "semana":
        inicio = (hoje - timedelta(days=hoje.weekday())).isoformat()
        titulo = f"Resumo da Semana"
        subtitulo = f"{inicio} a {hoje.isoformat()}"
    elif periodo == "mes":
        inicio = hoje.replace(day=1).isoformat()
        titulo = f"Resumo do Mês"
        subtitulo = f"{hoje.strftime('%B %Y')}"
    else:
        inicio = "2000-01-01"
        titulo = "Progresso Total"
        subtitulo = "Desde o início"

    # Horas estudadas no período
    horas = conn.execute("""
        SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo
        WHERE user_id = ? AND data >= ?
    """, (user_id, inicio)).fetchone()[0]

    # Questões resolvidas
    questoes = conn.execute("""
        SELECT COUNT(*) as total, COALESCE(SUM(acertou), 0) as acertos
        FROM questoes_respostas WHERE user_id = ? AND data >= ?
    """, (user_id, inicio)).fetchone()
    total_q = questoes["total"]
    acertos_q = questoes["acertos"]
    pct_acerto = round(acertos_q / total_q * 100, 1) if total_q > 0 else 0

    # Streak
    try:
        from utils import get_streak_info
        streak_info = get_streak_info(conn, user_id=user_id)
        streak = streak_info.get("streak_atual", 0)
    except Exception:
        streak = 0

    # Dias ativos no período
    dias_ativos = conn.execute("""
        SELECT COUNT(DISTINCT data) FROM streaks
        WHERE user_id = ? AND data >= ?
        AND (horas_estudadas > 0 OR questoes_resolvidas > 0 OR flashcards_revisados > 0)
    """, (user_id, inicio)).fetchone()[0]

    # Melhor matéria (maior % acerto com >10 questões)
    melhor = conn.execute("""
        SELECT q.materia, ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ?
        GROUP BY q.materia HAVING COUNT(*) >= 5
        ORDER BY pct DESC LIMIT 1
    """, (user_id, inicio)).fetchone()

    # Pior matéria
    pior = conn.execute("""
        SELECT q.materia, ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ?
        GROUP BY q.materia HAVING COUNT(*) >= 5
        ORDER BY pct ASC LIMIT 1
    """, (user_id, inicio)).fetchone()

    # Conquistas do período
    conquistas = []
    if horas >= 10:
        conquistas.append(f"🏆 {horas:.1f}h estudadas")
    if total_q >= 50:
        conquistas.append(f"💯 {total_q} questões resolvidas")
    if streak >= 7:
        conquistas.append(f"🔥 Streak de {streak} dias")
    if pct_acerto >= 70:
        conquistas.append(f"🎯 {pct_acerto}% de acerto")

    dias_semana = 7 if periodo == "semana" else 30 if periodo == "mes" else dias_ativos

    return {
        "titulo": titulo,
        "subtitulo": subtitulo,
        "stats": {
            "horas": round(horas, 1),
            "questoes": total_q,
            "pct_acerto": pct_acerto,
            "streak": streak,
            "dias_ativos": dias_ativos,
            "dias_total": dias_semana,
        },
        "destaques": {
            "melhor_materia": {"materia": melhor["materia"], "pct": melhor["pct"]} if melhor else None,
            "pior_materia": {"materia": pior["materia"], "pct": pior["pct"]} if pior else None,
        },
        "conquistas": conquistas,
        "share_text": f"📊 {titulo}\n{subtitulo}\n\n{horas:.1f}h estudadas\n{total_q} questões ({pct_acerto}% acerto)\n🔥{streak} dias de streak\n{'/'.join(conquistas[:2])}\n\n#ConcurseiroOS #EstudosPraConcurso",
    }

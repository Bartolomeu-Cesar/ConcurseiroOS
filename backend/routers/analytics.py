"""Router de Analytics e Relatórios Avançados."""
import json
import math
import re
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from database import get_db_session
from deps import get_user_id
from logger import log
from services import get_acertos_por_materia, get_horas_estudadas
from utils import calculate_streak, paginate, sql_paginate, today_str

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

    return {
        "data": today_str(),
        "horas": hoje["horas_estudadas"] if hoje else 0,
        "questoes": hoje["questoes_resolvidas"] if hoje else 0,
        "flashcards": hoje["flashcards_revisados"] if hoje else 0,
        "sessoes": [{"materia": r[0], "horas": round(r[1], 1)} for r in sessoes],
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
    query = "SELECT materia, COUNT(*) as total, SUM(CASE WHEN status='Concluído' THEN 1 ELSE 0 END) as done, SUM(horas_estudadas) as horas FROM edital WHERE user_id = ?"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
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


@router.get("/api/linha-tempo", summary="Linha do tempo")
def linha_tempo(page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT data, materia, horas, tipo FROM sessoes_estudo WHERE user_id = ? ORDER BY data DESC, id DESC"
    if page is None:
        rows = conn.execute(query, (user_id,)).fetchall()
        return [dict(r) for r in rows][:50]
    return sql_paginate(conn, query, (user_id,), page, limit)


@router.get("/api/exportar-stats")
def exportar_estatisticas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    data = {
        "exportado_em": datetime.now().isoformat(),
        "edital": [dict(r) for r in conn.execute("SELECT * FROM edital WHERE user_id = ?", (user_id,)).fetchall()],
        "questoes_stats": {
            "total": conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0],
            "acertos": conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0],
        },
        "sessoes": [dict(r) for r in conn.execute("SELECT * FROM sessoes_estudo WHERE user_id = ? ORDER BY data DESC LIMIT 100", (user_id,)).fetchall()],
        "streaks": [dict(r) for r in conn.execute("SELECT * FROM streaks WHERE user_id = ? ORDER BY data DESC LIMIT 30", (user_id,)).fetchall()],
        "simulados": [dict(r) for r in conn.execute("SELECT * FROM simulados WHERE user_id = ?", (user_id,)).fetchall()],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="estatisticas_completas.json", background=None)


@router.get("/api/exportar-resumo")
def exportar_resumo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    editais = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as done,
               SUM(horas_estudadas) as horas
        FROM edital WHERE user_id = ? GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """, (user_id,)).fetchall()
    q_stats = conn.execute("SELECT COUNT(*), SUM(acertou) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()
    streaks = conn.execute("SELECT data, horas_estudadas, questoes_resolvidas FROM streaks WHERE user_id = ? ORDER BY data DESC LIMIT 30", (user_id,)).fetchall()

    html = f"""<!DOCTYPE html>
<html><head><meta charset='UTF-8'><title>Resumo de Estudos - ConcurseiroOS</title>
<style>
  body {{ font-family: sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }}
  h1 {{ color: #6c3483; border-bottom: 2px solid #6c3483; padding-bottom: 8px; }}
  h2 {{ color: #2980b9; margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f4f4f4; }}
  .stat {{ display: inline-block; margin: 8px 16px 8px 0; padding: 8px 16px; background: #f0f0f0; border-radius: 8px; }}
  .stat strong {{ font-size: 1.3rem; }}
  @media print {{ body {{ padding: 20px; }} }}
</style></head><body>
<h1>📚 Resumo de Estudos - ConcurseiroOS</h1>
<p>Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}</p>
<h2>📊 Estatísticas Gerais</h2>
<div class='stat'>Questões: <strong>{q_stats[0] or 0}</strong> resolvidas ({q_stats[1] or 0} acertos)</div>
<div class='stat'>Aproveitamento: <strong>{round((q_stats[1]/q_stats[0]*100) if q_stats[0] else 0, 1)}%</strong></div>
<h2>📋 Progresso por Edital/Cargo</h2>
<table><tr><th>Edital</th><th>Cargo</th><th>Tópicos</th><th>Concluídos</th><th>%</th><th>Horas</th></tr>"""
    for e in editais:
        pct = round(e[3] / e[2] * 100, 1) if e[2] > 0 else 0
        html += f"<tr><td>{e[0]}</td><td>{e[1]}</td><td>{e[2]}</td><td>{e[3]}</td><td>{pct}%</td><td>{e[4]:.1f}h</td></tr>"
    html += "</table>"
    if streaks:
        html += "<h2>🔥 Últimos 30 dias de Estudo</h2><table><tr><th>Data</th><th>Horas</th><th>Questões</th></tr>"
        for s in streaks:
            html += f"<tr><td>{s[0]}</td><td>{s[1]:.1f}h</td><td>{s[2]}</td></tr>"
        html += "</table>"
    html += "</body></html>"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
    tmp.write(html)
    tmp.close()
    return FileResponse(tmp.name, media_type="text/html", filename="resumo_estudos.html", background=None)


@router.get("/api/exportar-tudo")
def exportar_tudo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    data = {
        "exportado_em": datetime.now().isoformat(), "versao": "2.0",
        "edital": [dict(r) for r in conn.execute("SELECT * FROM edital WHERE user_id = ?", (user_id,)).fetchall()],
        "questoes": [dict(r) for r in conn.execute("SELECT * FROM questoes WHERE user_id = ?", (user_id,)).fetchall()],
        "flashcards": [dict(r) for r in conn.execute("SELECT * FROM flashcards WHERE user_id = ?", (user_id,)).fetchall()],
        "questoes_respostas": [dict(r) for r in conn.execute("SELECT * FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchall()],
        "sessoes_estudo": [dict(r) for r in conn.execute("SELECT * FROM sessoes_estudo WHERE user_id = ?", (user_id,)).fetchall()],
        "streaks": [dict(r) for r in conn.execute("SELECT * FROM streaks WHERE user_id = ?", (user_id,)).fetchall()],
        "simulados": [dict(r) for r in conn.execute("SELECT * FROM simulados WHERE user_id = ?", (user_id,)).fetchall()],
        "ciclo_estudos": [dict(r) for r in conn.execute("SELECT * FROM ciclo_estudos WHERE user_id = ?", (user_id,)).fetchall()],
        "metas_config": [dict(r) for r in conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchall()],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="concurseiro_backup_completo.json", background=None)


@router.post("/api/importar-tudo")
async def importar_tudo(file: UploadFile = File(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    content = await file.read()
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido") from None

    count = 0
    for item in data.get("flashcards", []):
        conn.execute("INSERT OR IGNORE INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, user_id) VALUES (?, ?, ?, ?, ?)",
                     (item["pergunta"], item["resposta"], item.get("proxima_revisao", today_str()), item.get("intervalo_dias", 1), user_id))
        count += 1
    for item in data.get("questoes", []):
        conn.execute("""INSERT OR IGNORE INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, created_at, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.get("materia", ""), item.get("topico", ""), item.get("enunciado", ""),
             item.get("alternativa_a", ""), item.get("alternativa_b", ""), item.get("alternativa_c", ""),
             item.get("alternativa_d", ""), item.get("alternativa_e", ""), item.get("resposta_correta", ""),
             item.get("explicacao", ""), item.get("dificuldade", "Médio"), item.get("created_at", today_str()), user_id))
        count += 1
    conn.commit()
    return {"ok": True, "importados": count}


@router.get("/api/compartilhar")
def gerar_compartilhamento(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?", (user_id,)).fetchone()[0]
    questoes = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    topicos = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)).fetchone()[0]
    total_topicos = conn.execute("SELECT COUNT(*) FROM edital WHERE user_id = ?", (user_id,)).fetchone()[0]
    streak_info = calculate_streak(conn, user_id)
    streak = streak_info["streak_atual"]
    pct = round(topicos / total_topicos * 100, 1) if total_topicos > 0 else 0
    accuracy = round(acertos / questoes * 100, 1) if questoes > 0 else 0

    return {
        "texto": f"📚 ConcurseiroOS | {streak}🔥 dias | {round(horas, 1)}h estudadas | {questoes} questões ({accuracy}%) | {pct}% do edital",
        "stats": {"horas": round(horas, 1), "questoes": questoes, "accuracy": accuracy,
                  "streak": streak, "topicos": topicos, "total_topicos": total_topicos, "pct_edital": pct}
    }


@router.get("/api/status-rapido")
def status_rapido(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)).fetchone()[0]
    topicos_done = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)).fetchone()[0]
    topicos_total = conn.execute("SELECT COUNT(*) FROM edital WHERE user_id = ?", (user_id,)).fetchone()[0]
    streak_info = calculate_streak(conn, user_id)
    return {
        "streak": streak_info["streak_atual"],
        "horas_hoje": hoje["horas_estudadas"] if hoje else 0,
        "questoes_hoje": hoje["questoes_resolvidas"] if hoje else 0,
        "flashcards_pendentes": flash,
        "edital_pct": round(topicos_done / topicos_total * 100, 1) if topicos_total > 0 else 0,
        "topicos": f"{topicos_done}/{topicos_total}"
    }


@router.get("/api/widget")
def widget_resumo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)).fetchone()[0]
    try:
        prova = conn.execute("""
            SELECT cargo, data_prova_objetiva FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?
            ORDER BY data_prova_objetiva LIMIT 1
        """, (user_id,)).fetchone()
    except Exception:
        prova = None
    return {
        "streak_hoje": bool(hoje), "horas_hoje": hoje["horas_estudadas"] if hoje else 0,
        "questoes_hoje": hoje["questoes_resolvidas"] if hoje else 0,
        "flashcards_pendentes": flash,
        "proxima_prova": {"cargo": prova[0], "data": prova[1]} if prova else None
    }


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
        retencao = math.exp(-t / S)
        retencao_pct = round(retencao * 100, 1)
        resultado.append({
            "id": r[0], "materia": r[3], "topico": r[4], "retencao_pct": retencao_pct,
            "dias_desde_revisao": t, "proxima_revisao": proxima_revisao, "urgente": retencao_pct < 50
        })

    resultado.sort(key=lambda x: x["retencao_pct"])
    return resultado


@router.get("/api/raio-x")
def raio_x_edital(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes WHERE user_id = ?", (user_id,)).fetchone()[0]
    questoes_por_mat = conn.execute("SELECT materia, COUNT(*) as qtd FROM questoes WHERE user_id = ? GROUP BY materia ORDER BY qtd DESC", (user_id,)).fetchall()
    horas_por_mat = conn.execute("SELECT materia, SUM(horas) as total FROM sessoes_estudo WHERE user_id = ? GROUP BY materia", (user_id,)).fetchall()
    horas_map = {r[0]: r[1] for r in horas_por_mat}
    acertos_por_mat = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id WHERE qr.user_id = ? GROUP BY q.materia
    """, (user_id,)).fetchall()
    acerto_map = {r[0]: round((r[2] or 0) / r[1] * 100, 1) if r[1] > 0 else 0 for r in acertos_por_mat}
    total_horas = sum(horas_map.values()) if horas_map else 0

    materias = []
    for r in questoes_por_mat:
        mat, qtd = r[0], r[1]
        peso_pct = round(qtd / total_questoes * 100, 1) if total_questoes > 0 else 0
        horas_est = round(horas_map.get(mat, 0), 1)
        pct_horas = round(horas_est / total_horas * 100, 1) if total_horas > 0 else 0
        pct_acerto = acerto_map.get(mat, 0)
        if total_horas == 0 or peso_pct == 0:
            balanceamento = "sem_dados"
        elif pct_horas >= peso_pct * 1.5:
            balanceamento = "superestudado"
        elif pct_horas <= peso_pct * 0.5:
            balanceamento = "subestudado"
        else:
            balanceamento = "equilibrado"
        materias.append({"materia": mat, "questoes": qtd, "peso_pct": peso_pct,
                         "horas_estudadas": horas_est, "pct_acerto": pct_acerto, "balanceamento": balanceamento})
    return {"total_questoes": total_questoes, "materias": materias}


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

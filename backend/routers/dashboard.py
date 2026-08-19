import json
import math
import re
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from database import get_db_session
from logger import log
from models import DashboardResponse
from utils import calculate_streak, paginate, today_str

router = APIRouter(prefix="", tags=["Dashboard & Analytics"])


@router.get("/api/dashboard", response_model=DashboardResponse, summary="Dashboard principal", description="Retorna métricas consolidadas: horas, progresso, questões, flashcards")
def get_dashboard(conn=Depends(get_db_session)):
    # Horas por dia (últimos 14 dias)
    horas_dia = conn.execute("""
        SELECT data, SUM(horas) as total_horas
        FROM sessoes_estudo
        WHERE data >= ?
        GROUP BY data ORDER BY data
    """, ((date.today() - timedelta(days=13)).isoformat(),)).fetchall()

    # Total de horas
    total_horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]

    # Progresso do edital
    edital_total = conn.execute("SELECT COUNT(*) FROM edital").fetchone()[0]
    edital_concluido = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído'").fetchone()[0]

    # Questões stats
    questoes_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    questoes_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]

    # Evolução de acertos por dia (últimos 14 dias)
    acertos_dia = conn.execute("""
        SELECT data,
               COUNT(*) as total,
               SUM(acertou) as acertos
        FROM questoes_respostas
        WHERE data >= ?
        GROUP BY data ORDER BY data
    """, ((date.today() - timedelta(days=13)).isoformat(),)).fetchall()

    # Horas por matéria
    horas_materia = conn.execute("""
        SELECT materia, SUM(horas) as total
        FROM sessoes_estudo
        GROUP BY materia ORDER BY total DESC
    """).fetchall()

    # Flashcards pendentes
    flashcards_pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)
    ).fetchone()[0]

    # Total flashcards
    flashcards_total = conn.execute("SELECT COUNT(*) FROM flashcards").fetchone()[0]

    return {
        "horas_por_dia": [dict(r) for r in horas_dia],
        "total_horas": round(total_horas, 1),
        "edital": {"total": edital_total, "concluido": edital_concluido},
        "questoes": {
            "total": questoes_total,
            "acertos": questoes_acertos,
            "percentual": round((questoes_acertos / questoes_total * 100) if questoes_total > 0 else 0, 1)
        },
        "acertos_por_dia": [dict(r) for r in acertos_dia],
        "horas_por_materia": [dict(r) for r in horas_materia],
        "flashcards": {"pendentes": flashcards_pendentes, "total": flashcards_total}
    }


@router.get("/api/relatorio-semanal", summary="Relatório semanal", description="Relatório consolidado da semana: horas, questões, matérias fracas e sugestões")
def relatorio_semanal(conn=Depends(get_db_session)):
    inicio_semana = (date.today() - timedelta(days=date.today().weekday())).isoformat()

    # Horas da semana
    horas = conn.execute("""
        SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ?
    """, (inicio_semana,)).fetchone()[0]

    # Questões da semana
    questoes = conn.execute("""
        SELECT COUNT(*) as total, SUM(acertou) as acertos
        FROM questoes_respostas WHERE data >= ?
    """, (inicio_semana,)).fetchone()

    # Matéria mais fraca (menor % acerto com pelo menos 3 questões)
    materia_fraca = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.data >= ?
        GROUP BY q.materia
        HAVING total >= 3
        ORDER BY pct ASC
        LIMIT 3
    """, (inicio_semana,)).fetchall()

    # Dias estudados na semana
    dias = conn.execute("""
        SELECT COUNT(DISTINCT data) FROM streaks
        WHERE data >= ? AND (horas_estudadas > 0 OR questoes_resolvidas > 0)
    """, (inicio_semana,)).fetchone()[0]

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
def resumo_diario(conn=Depends(get_db_session)):
    """Resumo do dia: o que foi feito + sugestão para amanhã"""
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()

    # Sessões de hoje
    sessoes = conn.execute("SELECT materia, SUM(horas) FROM sessoes_estudo WHERE data = ? GROUP BY materia", (today_str(),)).fetchall()

    # Questões de hoje
    q_hoje = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id=qr.questao_id
        WHERE qr.data = ? GROUP BY q.materia
    """, (today_str(),)).fetchall()

    # Sugestão para amanhã: matéria menos estudada
    menos_estudada = conn.execute("""
        SELECT materia, SUM(horas_estudadas) as h FROM edital
        WHERE status != 'Concluído'
        GROUP BY materia ORDER BY h ASC LIMIT 3
    """).fetchall()

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
def pratica_deliberada(conn=Depends(get_db_session)):
    """Identifica as matérias com pior desempenho e sugere foco"""
    materias = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total_questoes,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as percentual
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
        ORDER BY percentual ASC
    """).fetchall()

    # Matérias com questões disponíveis mas nunca respondidas
    nao_estudadas = conn.execute("""
        SELECT DISTINCT materia FROM questoes
        WHERE materia NOT IN (
            SELECT DISTINCT q.materia FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
        )
    """).fetchall()

    sugestoes = []
    for m in materias:
        if m[3] < 70:  # Menos de 70% de acerto
            sugestoes.append({
                "materia": m[0],
                "total_questoes": m[1],
                "percentual": m[3],
                "prioridade": "ALTA" if m[3] < 50 else "MÉDIA"
            })

    return {
        "materias_para_focar": sugestoes,
        "materias_nao_estudadas": [r[0] for r in nao_estudadas],
        "recomendacao": "Foque nas matérias com menor percentual de acerto. Resolva pelo menos 10 questões de cada antes de avançar."
    }


@router.get("/api/radar")
def get_radar(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Retorna dados para gráfico radar de desempenho por matéria"""
    # Progresso do edital por matéria
    query = """
        SELECT materia,
               COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos,
               SUM(horas_estudadas) as horas
        FROM edital WHERE 1=1
    """
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " GROUP BY materia ORDER BY materia"

    materias_edital = conn.execute(query, params).fetchall()

    # Acerto em questões por matéria
    questoes_por_mat = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
    """).fetchall()
    q_map = {r[0]: {"total": r[1], "acertos": r[2]} for r in questoes_por_mat}

    # Montar dados do radar
    radar_data = []
    for m in materias_edital:
        materia = m[0]
        total = m[1]
        concluidos = m[2]
        horas = m[3] or 0

        # Score do edital (0-100)
        pct_edital = (concluidos / total * 100) if total > 0 else 0

        # Score de questões (0-100)
        q_data = q_map.get(materia, {"total": 0, "acertos": 0})
        pct_questoes = (q_data["acertos"] / q_data["total"] * 100) if q_data["total"] > 0 else 0

        # Score composto (média)
        score = (pct_edital + pct_questoes) / 2 if q_data["total"] > 0 else pct_edital

        radar_data.append({
            "materia": materia,
            "score": round(score, 1),
            "pct_edital": round(pct_edital, 1),
            "pct_questoes": round(pct_questoes, 1),
            "horas": round(horas, 1),
            "topicos_total": total,
            "topicos_concluidos": concluidos
        })

    return radar_data


@router.get("/api/heatmap")
def get_heatmap(conn=Depends(get_db_session)):
    """Retorna dados para heatmap de estudos (365 dias)"""
    inicio = (date.today() - timedelta(days=365)).isoformat()
    rows = conn.execute("""
        SELECT data, horas_estudadas, questoes_resolvidas, flashcards_revisados
        FROM streaks WHERE data >= ? ORDER BY data
    """, (inicio,)).fetchall()

    result = []
    for r in rows:
        horas = r[1] or 0
        questoes = r[2] or 0
        flashcards = r[3] or 0
        # Intensidade combinada: horas + questões + flashcards
        # Cada atividade contribui para a intensidade:
        # - 0.5h = 1 nível, 1h = 2 níveis, 2h+ = 3-4 níveis
        # - 10 questões = 1 nível, 20+ = 2 níveis
        # - 5 flashcards = 1 nível, 15+ = 2 níveis
        score = (horas / 0.5) + (questoes / 10) + (flashcards / 5)
        intensidade = min(4, max(1, int(score))) if score > 0 else 0
        result.append({
            "data": r[0], "horas": horas, "questoes": questoes,
            "flashcards": flashcards, "intensidade": intensidade
        })
    return result


@router.get("/api/projecao-nota")
def projecao_nota(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Projeta nota na prova baseado em desempenho por matéria"""
    # Buscar matérias do edital com pesos estimados
    query = "SELECT DISTINCT materia FROM edital WHERE 1=1"
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    materias = [r[0] for r in conn.execute(query, params).fetchall()]

    # Acerto por matéria
    total_pontos = 0
    total_possiveis = 0
    detalhes = []
    for mat in materias:
        q = conn.execute("""
            SELECT COUNT(*) as total, SUM(acertou) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id=qr.questao_id
            WHERE q.materia = ?
        """, (mat,)).fetchone()
        total_q = q[0] or 0
        acertos = q[1] or 0
        pct = (acertos / total_q * 100) if total_q > 0 else 50  # 50% default se sem dados
        peso = 1  # peso igual por matéria (simplificado)
        pontos = pct * peso
        total_pontos += pontos
        total_possiveis += 100 * peso
        detalhes.append({"materia": mat, "pct_acerto": round(pct, 1), "questoes": total_q})

    nota_projetada = (total_pontos / total_possiveis * 100) if total_possiveis > 0 else 0

    return {
        "nota_projetada": round(nota_projetada, 1),
        "nota_corte_estimada": 60.0,
        "aprovado_estimado": nota_projetada >= 60,
        "materias": sorted(detalhes, key=lambda x: x['pct_acerto']),
        "total_materias": len(materias)
    }


@router.get("/api/previsao-aprovacao")
def previsao_aprovacao(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Calcula previsão de aprovação baseado em progresso e acertos"""
    # Progresso do edital
    query_base = "SELECT COUNT(*) FROM edital WHERE 1=1"
    query_done = "SELECT COUNT(*) FROM edital WHERE status = 'Concluído'"
    params = []
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

    # % acerto em questões
    q_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    q_acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]

    # Horas estudadas
    horas_total = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]

    # Cálculo da previsão (fórmula simplificada)
    pct_edital = (topicos_concluidos / total_topicos * 100) if total_topicos > 0 else 0
    pct_questoes = (q_acertos / q_total * 100) if q_total > 0 else 0

    # Pesos: 40% edital concluído + 50% acerto questões + 10% horas
    fator_horas = min(100, horas_total * 2)  # 50h = 100%
    score = (pct_edital * 0.4) + (pct_questoes * 0.5) + (fator_horas * 0.1)

    # Classificação
    if score >= 80:
        nivel = "Excelente"
        emoji = "🏆"
    elif score >= 60:
        nivel = "Bom"
        emoji = "✅"
    elif score >= 40:
        nivel = "Regular"
        emoji = "⚠️"
    elif score >= 20:
        nivel = "Iniciante"
        emoji = "📖"
    else:
        nivel = "Começando"
        emoji = "🌱"

    return {
        "score": round(score, 1),
        "nivel": nivel,
        "emoji": emoji,
        "detalhes": {
            "edital_pct": round(pct_edital, 1),
            "questoes_pct": round(pct_questoes, 1),
            "horas_total": round(horas_total, 1),
            "topicos_concluidos": topicos_concluidos,
            "topicos_total": total_topicos,
            "questoes_total": q_total,
            "questoes_acertos": q_acertos
        }
    }


@router.get("/api/previsao-data-aprovacao")
def previsao_data_aprovacao(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Calcula previsão de data de aprovação baseado no ritmo atual"""
    try:
        # Topicos restantes
        query = "SELECT COUNT(*) FROM edital WHERE status != 'Concluído'"
        params = []
        if edital_nome:
            query += " AND edital_nome = ?"
            params.append(edital_nome)
        if cargo:
            query += " AND cargo = ?"
            params.append(cargo)
        restantes = int(conn.execute(query, params).fetchone()[0] or 0)

        # Ritmo: horas nas últimas 4 semanas
        quatro_semanas = (date.today() - timedelta(days=28)).isoformat()
        total_horas_4sem = float(conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ?", (quatro_semanas,)
        ).fetchone()[0] or 0)
    except Exception:
        return {"semanas_restantes": None, "data_prevista": None,
                "message": "Erro ao calcular. Estude mais para gerar previsão.", "restantes": 0}

    horas_por_semana = total_horas_4sem / 4 if total_horas_4sem > 0 else 0
    topicos_por_semana = horas_por_semana * 2

    if topicos_por_semana <= 0 or restantes <= 0:
        return {"semanas_restantes": None, "data_prevista": None,
                "message": "Estude mais para gerar previsão.", "restantes": restantes}

    semanas = restantes / topicos_por_semana
    # Limitar a no máximo 520 semanas (10 anos) para evitar overflow
    semanas = min(semanas, 520)
    data_prevista = (date.today() + timedelta(weeks=int(semanas))).isoformat()

    return {
        "semanas_restantes": round(semanas, 1),
        "data_prevista": data_prevista,
        "restantes": restantes,
        "ritmo_semanal": round(topicos_por_semana, 1),
        "horas_semana": round(horas_por_semana, 1)
    }


@router.get("/api/analise-erros")
def analise_padroes_erro(conn=Depends(get_db_session)):
    """Analisa padrões de erro para sugerir o que revisar"""
    # Top matérias com mais erros
    erros_por_materia = conn.execute("""
        SELECT q.materia, COUNT(*) as erros,
               (SELECT COUNT(*) FROM questoes_respostas qr2 JOIN questoes q2 ON q2.id=qr2.questao_id WHERE q2.materia=q.materia) as total
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0
        GROUP BY q.materia
        ORDER BY erros DESC
    """).fetchall()

    # Top tópicos mais errados
    erros_por_topico = conn.execute("""
        SELECT q.materia, q.enunciado, COUNT(*) as vezes_errado
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0
        GROUP BY qr.questao_id
        ORDER BY vezes_errado DESC
        LIMIT 10
    """).fetchall()

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
def comparativo_cargos(edital1: str = "", cargo1: str = "", edital2: str = "", cargo2: str = "", conn=Depends(get_db_session)):
    """Compara disciplinas entre dois cargos/editais"""
    mat1 = set(r[0] for r in conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE edital_nome = ? AND cargo = ?", (edital1, cargo1)
    ).fetchall())
    mat2 = set(r[0] for r in conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE edital_nome = ? AND cargo = ?", (edital2, cargo2)
    ).fetchall())
    comuns = sorted(mat1 & mat2)
    apenas1 = sorted(mat1 - mat2)
    apenas2 = sorted(mat2 - mat1)
    return {
        "cargo1": f"{edital1} - {cargo1}",
        "cargo2": f"{edital2} - {cargo2}",
        "comuns": comuns,
        "apenas_cargo1": apenas1,
        "apenas_cargo2": apenas2,
        "total_comuns": len(comuns),
        "total_apenas1": len(apenas1),
        "total_apenas2": len(apenas2)
    }


@router.get("/api/comparador-progresso")
def comparador_progresso(conn=Depends(get_db_session)):
    """Compara progresso entre todos os editais/cargos"""
    rows = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status='Concluído' THEN 1 ELSE 0 END) as done,
               SUM(horas_estudadas) as horas
        FROM edital GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """).fetchall()
    return [{
        "edital": r[0], "cargo": r[1], "total": r[2],
        "concluidos": r[3] or 0,
        "pct": round((r[3] or 0) / r[2] * 100, 1) if r[2] > 0 else 0,
        "horas": round(r[4] or 0, 1)
    } for r in rows]


@router.get("/api/planejador-aprovacao")
def planejador_aprovacao(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Calcula o que falta para atingir meta de aprovação por matéria"""
    query = "SELECT materia, COUNT(*) as total, SUM(CASE WHEN status='Concluído' THEN 1 ELSE 0 END) as done, SUM(horas_estudadas) as horas FROM edital WHERE 1=1"
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " GROUP BY materia ORDER BY materia"
    materias = conn.execute(query, params).fetchall()

    # Acertos por matéria
    q_stats = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
    """).fetchall()
    q_map = {r[0]: {"total": r[1], "acertos": r[2] or 0} for r in q_stats}

    META_EDITAL = 70  # % mínimo do edital concluído
    META_QUESTOES = 70  # % mínimo de acerto

    plano = []
    for m in materias:
        materia, total, done, horas = m[0], m[1], m[2] or 0, m[3] or 0
        pct_edital = (done / total * 100) if total > 0 else 0
        q = q_map.get(materia, {"total": 0, "acertos": 0})
        pct_questoes = (q["acertos"] / q["total"] * 100) if q["total"] > 0 else 0

        topicos_faltam = max(0, int(total * META_EDITAL / 100) - done)
        questoes_precisa = max(0, 20 - q["total"])  # mínimo 20 questões por matéria

        status = "ok" if pct_edital >= META_EDITAL and pct_questoes >= META_QUESTOES else "atencao" if pct_edital >= 50 or pct_questoes >= 50 else "critico"

        plano.append({
            "materia": materia,
            "pct_edital": round(pct_edital, 1),
            "pct_questoes": round(pct_questoes, 1),
            "topicos_faltam": topicos_faltam,
            "questoes_precisa": questoes_precisa,
            "horas_estudadas": round(horas, 1),
            "status": status
        })

    return {"meta_edital": META_EDITAL, "meta_questoes": META_QUESTOES, "materias": plano}


@router.get("/api/plano-automatico")
def plano_automatico(edital_nome: str = "", cargo: str = "", horas_dia: float = 3.0, conn=Depends(get_db_session)):
    """Gera plano de estudo automático baseado no edital e data da prova"""
    # Buscar data da prova
    try:
        prova = conn.execute("""
            SELECT data_prova_objetiva FROM edital_info
            WHERE edital_nome = ? AND cargo = ? AND data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital'
        """, (edital_nome, cargo)).fetchone()
    except Exception:
        prova = None

    # Matérias com progresso
    query = "SELECT materia, COUNT(*) as total, SUM(CASE WHEN status='Concluído' THEN 1 ELSE 0 END) as done FROM edital WHERE 1=1"
    params = []
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " GROUP BY materia ORDER BY materia"
    materias = conn.execute(query, params).fetchall()

    # Calcular dias até a prova
    dias_ate_prova = 90  # default
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

    # Distribuir horas proporcionalmente aos tópicos restantes
    plano = []
    for m in materias:
        restantes = m[1] - (m[2] or 0)
        if restantes <= 0:
            continue
        proporcao = restantes / total_topicos_restantes if total_topicos_restantes > 0 else 0
        horas_materia = round(total_horas_disponiveis * proporcao, 1)
        horas_semana = round(horas_materia / (dias_ate_prova / 7), 1)
        plano.append({
            "materia": m[0],
            "topicos_restantes": restantes,
            "horas_total": horas_materia,
            "horas_semana": horas_semana
        })

    return {
        "dias_ate_prova": dias_ate_prova,
        "horas_dia": horas_dia,
        "total_horas": round(total_horas_disponiveis, 0),
        "topicos_restantes": total_topicos_restantes,
        "plano": sorted(plano, key=lambda x: -x['topicos_restantes'])
    }


@router.get("/api/linha-tempo", summary="Linha do tempo", description="Histórico de sessões de estudo com paginação opcional")
def linha_tempo(page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session)):
    """Histórico de sessões de estudo (timeline)"""
    rows = conn.execute("""
        SELECT data, materia, horas, tipo FROM sessoes_estudo
        ORDER BY data DESC, id DESC
    """).fetchall()

    items = [dict(r) for r in rows]

    # Se page não fornecido, retorna array completo (retrocompatibilidade) — max 50
    if page is None:
        return items[:50]

    return paginate(items, page, limit)


@router.get("/api/exportar-stats")
def exportar_estatisticas(conn=Depends(get_db_session)):
    data = {
        "exportado_em": datetime.now().isoformat(),
        "edital": [dict(r) for r in conn.execute("SELECT * FROM edital").fetchall()],
        "questoes_stats": {
            "total": conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0],
            "acertos": conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0],
        },
        "sessoes": [dict(r) for r in conn.execute("SELECT * FROM sessoes_estudo ORDER BY data DESC LIMIT 100").fetchall()],
        "streaks": [dict(r) for r in conn.execute("SELECT * FROM streaks ORDER BY data DESC LIMIT 30").fetchall()],
        "simulados": [dict(r) for r in conn.execute("SELECT * FROM simulados").fetchall()],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="estatisticas_completas.json", background=None)


@router.get("/api/exportar-resumo")
def exportar_resumo(conn=Depends(get_db_session)):
    """Gera um resumo completo em formato texto/HTML para impressão"""
    # Progresso por edital
    editais = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as done,
               SUM(horas_estudadas) as horas
        FROM edital GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """).fetchall()

    # Questões
    q_stats = conn.execute("SELECT COUNT(*), SUM(acertou) FROM questoes_respostas").fetchone()

    # Streaks
    streaks = conn.execute("SELECT data, horas_estudadas, questoes_resolvidas FROM streaks ORDER BY data DESC LIMIT 30").fetchall()

    # Montar HTML para impressão
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
def exportar_tudo(conn=Depends(get_db_session)):
    """Exporta TODOS os dados do usuário em JSON"""
    data = {
        "exportado_em": datetime.now().isoformat(),
        "versao": "2.0",
        "edital": [dict(r) for r in conn.execute("SELECT * FROM edital").fetchall()],
        "questoes": [dict(r) for r in conn.execute("SELECT * FROM questoes").fetchall()],
        "flashcards": [dict(r) for r in conn.execute("SELECT * FROM flashcards").fetchall()],
        "questoes_respostas": [dict(r) for r in conn.execute("SELECT * FROM questoes_respostas").fetchall()],
        "sessoes_estudo": [dict(r) for r in conn.execute("SELECT * FROM sessoes_estudo").fetchall()],
        "streaks": [dict(r) for r in conn.execute("SELECT * FROM streaks").fetchall()],
        "simulados": [dict(r) for r in conn.execute("SELECT * FROM simulados").fetchall()],
        "ciclo_estudos": [dict(r) for r in conn.execute("SELECT * FROM ciclo_estudos").fetchall()],
        "metas_config": [dict(r) for r in conn.execute("SELECT * FROM metas_config").fetchall()],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="concurseiro_backup_completo.json", background=None)


@router.post("/api/importar-tudo")
async def importar_tudo(file: UploadFile = File(...), conn=Depends(get_db_session)):
    """Importa backup completo de dados"""
    content = await file.read()
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido") from None

    count = 0

    # Importar flashcards
    for item in data.get("flashcards", []):
        conn.execute("INSERT OR IGNORE INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias) VALUES (?, ?, ?, ?)",
                     (item["pergunta"], item["resposta"], item.get("proxima_revisao", today_str()), item.get("intervalo_dias", 1)))
        count += 1

    # Importar questões
    for item in data.get("questoes", []):
        conn.execute("""INSERT OR IGNORE INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.get("materia", ""), item.get("topico", ""), item.get("enunciado", ""),
             item.get("alternativa_a", ""), item.get("alternativa_b", ""), item.get("alternativa_c", ""),
             item.get("alternativa_d", ""), item.get("alternativa_e", ""), item.get("resposta_correta", ""),
             item.get("explicacao", ""), item.get("dificuldade", "Médio"), item.get("created_at", today_str())))
        count += 1

    conn.commit()
    return {"ok": True, "importados": count}


@router.get("/api/compartilhar")
def gerar_compartilhamento(conn=Depends(get_db_session)):
    """Gera dados para compartilhamento de progresso em redes sociais"""
    horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]
    questoes = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
    acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]
    topicos = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído'").fetchone()[0]
    total_topicos = conn.execute("SELECT COUNT(*) FROM edital").fetchone()[0]

    streak_info = calculate_streak(conn)
    streak = streak_info["streak_atual"]

    pct = round(topicos / total_topicos * 100, 1) if total_topicos > 0 else 0
    accuracy = round(acertos / questoes * 100, 1) if questoes > 0 else 0

    return {
        "texto": f"📚 ConcurseiroOS | {streak}🔥 dias | {round(horas, 1)}h estudadas | {questoes} questões ({accuracy}%) | {pct}% do edital",
        "stats": {
            "horas": round(horas, 1),
            "questoes": questoes,
            "accuracy": accuracy,
            "streak": streak,
            "topicos": topicos,
            "total_topicos": total_topicos,
            "pct_edital": pct
        }
    }


@router.get("/api/status-rapido")
def status_rapido(conn=Depends(get_db_session)):
    """Página de status ultra-leve para mobile"""
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()
    flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)).fetchone()[0]
    topicos_done = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído'").fetchone()[0]
    topicos_total = conn.execute("SELECT COUNT(*) FROM edital").fetchone()[0]

    streak_info = calculate_streak(conn)
    streak = streak_info["streak_atual"]

    return {
        "streak": streak,
        "horas_hoje": hoje["horas_estudadas"] if hoje else 0,
        "questoes_hoje": hoje["questoes_resolvidas"] if hoje else 0,
        "flashcards_pendentes": flash,
        "edital_pct": round(topicos_done / topicos_total * 100, 1) if topicos_total > 0 else 0,
        "topicos": f"{topicos_done}/{topicos_total}"
    }


@router.get("/api/widget")
def widget_resumo(conn=Depends(get_db_session)):
    """Resumo ultra-leve para mobile/widget: streak, próxima revisão, countdown"""
    # Streak
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()

    # Flashcards pendentes
    flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ?", (today_str(),)).fetchone()[0]

    # Próxima prova
    try:
        prova = conn.execute("""
            SELECT cargo, data_prova_objetiva FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital'
            ORDER BY data_prova_objetiva LIMIT 1
        """).fetchone()
    except Exception:
        prova = None

    return {
        "streak_hoje": bool(hoje),
        "horas_hoje": hoje["horas_estudadas"] if hoje else 0,
        "questoes_hoje": hoje["questoes_resolvidas"] if hoje else 0,
        "flashcards_pendentes": flash,
        "proxima_prova": {"cargo": prova[0], "data": prova[1]} if prova else None
    }


@router.get("/api/curva-esquecimento")
def curva_esquecimento(edital_nome: str = "", cargo: str = "", materia: str = "", conn=Depends(get_db_session)):
    """Calcula a retenção estimada de cada tópico usando curva de esquecimento (e^(-t/S))"""
    query = """
        SELECT id, edital_nome, cargo, materia, topico, proxima_revisao,
               intervalo_revisao, easiness_factor_edital
        FROM edital
        WHERE proxima_revisao != '' AND proxima_revisao IS NOT NULL
    """
    params = []
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
        proxima_revisao = r[5]
        intervalo = r[6] or 1
        ef = r[7] if r[7] is not None else 2.5

        # Calcular dias desde última revisão
        # última revisão = proxima_revisao - intervalo
        try:
            prox = date.fromisoformat(proxima_revisao)
            ultima_revisao = prox - timedelta(days=intervalo)
            t = (hoje - ultima_revisao).days
        except (ValueError, TypeError):
            continue

        if t < 0:
            t = 0

        # S = estabilidade baseada no intervalo e EF
        S = intervalo * ef
        if S <= 0:
            S = 1

        # Retenção = e^(-t/S)
        retencao = math.exp(-t / S)
        retencao_pct = round(retencao * 100, 1)

        resultado.append({
            "id": r[0],
            "materia": r[3],
            "topico": r[4],
            "retencao_pct": retencao_pct,
            "dias_desde_revisao": t,
            "proxima_revisao": proxima_revisao,
            "urgente": retencao_pct < 50
        })

    # Ordenar por retenção (mais urgentes primeiro)
    resultado.sort(key=lambda x: x["retencao_pct"])
    return resultado


@router.get("/api/raio-x")
def raio_x_edital(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Raio-X do edital: peso estimado de cada matéria vs horas estudadas"""
    # Total de questões no banco
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes").fetchone()[0]

    # Questões por matéria
    questoes_por_mat = conn.execute("""
        SELECT materia, COUNT(*) as qtd FROM questoes GROUP BY materia ORDER BY qtd DESC
    """).fetchall()

    # Horas estudadas por matéria
    horas_por_mat = conn.execute("""
        SELECT materia, SUM(horas) as total FROM sessoes_estudo GROUP BY materia
    """).fetchall()
    horas_map = {r[0]: r[1] for r in horas_por_mat}

    # Acerto por matéria
    acertos_por_mat = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia
    """).fetchall()
    acerto_map = {r[0]: round((r[2] or 0) / r[1] * 100, 1) if r[1] > 0 else 0 for r in acertos_por_mat}

    # Total de horas estudadas
    total_horas = sum(horas_map.values()) if horas_map else 0

    materias = []
    for r in questoes_por_mat:
        mat = r[0]
        qtd = r[1]
        peso_pct = round(qtd / total_questoes * 100, 1) if total_questoes > 0 else 0
        horas_est = round(horas_map.get(mat, 0), 1)
        pct_horas = round(horas_est / total_horas * 100, 1) if total_horas > 0 else 0
        pct_acerto = acerto_map.get(mat, 0)

        # Diagnóstico de balanceamento
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
            "horas_estudadas": horas_est,
            "pct_acerto": pct_acerto,
            "balanceamento": balanceamento
        })

    return {
        "total_questoes": total_questoes,
        "materias": materias
    }


@router.get("/api/heatmap-erros")
def heatmap_erros(conn=Depends(get_db_session)):
    """Mapa de calor de erros por tópico — agrupa erros por matéria e tópico com intensidade"""
    log.info("GET /api/heatmap-erros")
    rows = conn.execute("""
        SELECT q.materia, q.topico, COUNT(*) as total,
               SUM(CASE WHEN qr.acertou=0 THEN 1 ELSE 0 END) as erros
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        GROUP BY q.materia, q.topico
        ORDER BY q.materia, erros DESC
    """).fetchall()

    # Agrupar por matéria
    materias_map = {}
    for r in rows:
        mat = r[0]
        topico = r[1] or "(sem tópico)"
        total = r[2]
        erros = r[3] or 0
        pct_erro = round((erros / total * 100) if total > 0 else 0, 1)

        # Calcular intensidade (0-4): 0=0%, 1=1-20%, 2=21-40%, 3=41-60%, 4=61%+
        if pct_erro == 0:
            intensidade = 0
        elif pct_erro <= 20:
            intensidade = 1
        elif pct_erro <= 40:
            intensidade = 2
        elif pct_erro <= 60:
            intensidade = 3
        else:
            intensidade = 4

        if mat not in materias_map:
            materias_map[mat] = {"materia": mat, "total_erros": 0, "total_questoes": 0, "topicos": []}

        materias_map[mat]["total_erros"] += erros
        materias_map[mat]["total_questoes"] += total
        materias_map[mat]["topicos"].append({
            "topico": topico,
            "erros": erros,
            "total": total,
            "pct_erro": pct_erro,
            "intensidade": intensidade
        })

    # Calcular pct_erro por matéria
    materias = []
    for mat_data in materias_map.values():
        total_q = mat_data["total_questoes"]
        total_e = mat_data["total_erros"]
        mat_data["pct_erro"] = round((total_e / total_q * 100) if total_q > 0 else 0, 1)
        materias.append(mat_data)

    # Ordenar por pct_erro desc
    materias.sort(key=lambda x: x["pct_erro"], reverse=True)

    return {"materias": materias}


@router.get("/api/evolucao")
def evolucao_semanal(semanas: int = 12, conn=Depends(get_db_session)):
    """Histórico de evolução por matéria, semana a semana com tendência"""
    log.info(f"GET /api/evolucao semanas={semanas}")
    # Buscar todas as respostas no período
    inicio = (date.today() - timedelta(weeks=semanas)).isoformat()
    rows = conn.execute("""
        SELECT qr.data, q.materia, qr.acertou
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.data >= ?
        ORDER BY qr.data
    """, (inicio,)).fetchall()

    # Organizar por semana ISO
    semanas_map = {}
    for r in rows:
        try:
            d = date.fromisoformat(r[0])
        except (ValueError, TypeError):
            continue
        iso = d.isocalendar()
        semana_key = f"{iso[0]}-W{iso[1]:02d}"
        # Início da semana (segunda)
        inicio_semana = (d - timedelta(days=d.weekday())).isoformat()

        if semana_key not in semanas_map:
            semanas_map[semana_key] = {"semana": semana_key, "inicio": inicio_semana, "materias": {}, "geral": {"questoes": 0, "acertos": 0}}

        mat = r[1]
        acertou = r[2]

        if mat not in semanas_map[semana_key]["materias"]:
            semanas_map[semana_key]["materias"][mat] = {"questoes": 0, "acertos": 0}

        semanas_map[semana_key]["materias"][mat]["questoes"] += 1
        semanas_map[semana_key]["materias"][mat]["acertos"] += (acertou or 0)
        semanas_map[semana_key]["geral"]["questoes"] += 1
        semanas_map[semana_key]["geral"]["acertos"] += (acertou or 0)

    # Formatar evolução
    evolucao = []
    for key in sorted(semanas_map.keys()):
        sem = semanas_map[key]
        materias_list = []
        for mat, dados in sem["materias"].items():
            pct = round((dados["acertos"] / dados["questoes"] * 100) if dados["questoes"] > 0 else 0, 1)
            materias_list.append({"materia": mat, "questoes": dados["questoes"], "acertos": dados["acertos"], "pct": pct})
        geral = sem["geral"]
        geral["pct"] = round((geral["acertos"] / geral["questoes"] * 100) if geral["questoes"] > 0 else 0, 1)
        evolucao.append({"semana": sem["semana"], "inicio": sem["inicio"], "materias": materias_list, "geral": geral})

    # Calcular tendência: comparar média das últimas 4 semanas vs anteriores
    tendencia = []
    if len(evolucao) >= 2:
        # Coletar todas as matérias
        todas_materias = set()
        for sem in evolucao:
            for m in sem["materias"]:
                todas_materias.add(m["materia"])

        ultimas_4 = evolucao[-4:] if len(evolucao) >= 4 else evolucao[-len(evolucao):]
        anteriores = evolucao[:-4] if len(evolucao) > 4 else []

        for mat in sorted(todas_materias):
            # Média últimas 4 semanas
            pcts_recentes = []
            for sem in ultimas_4:
                for m in sem["materias"]:
                    if m["materia"] == mat:
                        pcts_recentes.append(m["pct"])
            media_recente = sum(pcts_recentes) / len(pcts_recentes) if pcts_recentes else 0

            # Média anteriores
            pcts_anteriores = []
            for sem in anteriores:
                for m in sem["materias"]:
                    if m["materia"] == mat:
                        pcts_anteriores.append(m["pct"])
            media_anterior = sum(pcts_anteriores) / len(pcts_anteriores) if pcts_anteriores else media_recente

            delta = round(media_recente - media_anterior, 1)
            if delta > 3:
                tendencia_str = "melhorando"
            elif delta < -3:
                tendencia_str = "piorando"
            else:
                tendencia_str = "estavel"

            tendencia.append({"materia": mat, "tendencia": tendencia_str, "delta": delta})

    return {"semanas": semanas, "evolucao": evolucao, "tendencia": tendencia}

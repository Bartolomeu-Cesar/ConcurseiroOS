import codecs
import csv
import io
import random
import re
import tempfile

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from constants import DEFAULT_EXAM_DURATION_MIN, DEFAULT_EXAM_QUESTIONS, DEFAULT_TIME_PER_QUESTION_SEC
from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import QuestaoCreate, QuestaoResponse, QuestaoResposta, QuestaoRespostaResponse
from sanitize import sanitize_input
from schemas import QuestionLinkBatch, QuestionUpdate, RevisarErroRequest
from utils import paginate, sql_paginate, today_str, update_streak

router = APIRouter(prefix="", tags=["Questões"])


@router.get("/api/questoes", summary="Listar questões", description="Lista todas as questões do banco, com filtros por matéria/tópico e paginação opcional")
def list_questoes(
    materia: str = "",
    topico: str = "",
    dificuldade: str = "",
    banca: str = "",
    acertou: int | None = Query(None),
    respondidas: int | None = Query(None),
    data_inicio: str = "",
    data_fim: str = "",
    page: int | None = Query(None),
    limit: int = 50,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    params = []

    # Determinar tipo de query baseado nos filtros
    needs_join = acertou is not None or data_inicio or data_fim
    needs_not_in = respondidas == 0

    if needs_not_in:
        # Questões NÃO respondidas
        query = "SELECT q.* FROM questoes q WHERE q.user_id = ? AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)"
        params = [user_id, user_id]
        if materia:
            query += " AND q.materia = ?"
            params.append(materia)
        if topico:
            query += " AND q.topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND q.dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND q.banca = ?"
            params.append(banca)
    elif needs_join or respondidas == 1:
        # Questões com filtro por respostas (acertou/errou, datas)
        query = "SELECT DISTINCT q.* FROM questoes q JOIN questoes_respostas qr ON qr.questao_id = q.id WHERE q.user_id = ? AND qr.user_id = ?"
        params = [user_id, user_id]
        if materia:
            query += " AND q.materia = ?"
            params.append(materia)
        if topico:
            query += " AND q.topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND q.dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND q.banca = ?"
            params.append(banca)
        if acertou is not None:
            query += " AND qr.acertou = ?"
            params.append(acertou)
        if data_inicio:
            query += " AND qr.data >= ?"
            params.append(data_inicio)
        if data_fim:
            query += " AND qr.data <= ?"
            params.append(data_fim)
    else:
        # Query simples sem filtros de resposta
        query = "SELECT * FROM questoes WHERE user_id = ?"
        params = [user_id]
        if materia:
            query += " AND materia = ?"
            params.append(materia)
        if topico:
            query += " AND topico = ?"
            params.append(topico)
        if dificuldade:
            query += " AND dificuldade = ?"
            params.append(dificuldade)
        if banca:
            query += " AND banca = ?"
            params.append(banca)

    query += " ORDER BY q.id DESC" if (needs_join or needs_not_in or respondidas == 1) else " ORDER BY id DESC"

    return sql_paginate(conn, query, tuple(params), page, limit)


@router.get("/api/questoes/materias", summary="Listar matérias disponíveis",
            description="Retorna lista de matérias distintas presentes no banco de questões do usuário.")
def list_questoes_materias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT DISTINCT materia FROM questoes WHERE user_id = ? ORDER BY materia", (user_id,)).fetchall()
    return [r[0] for r in rows]


# Caderno de Erros (DEVE ficar antes de /api/questoes/{id})
@router.get("/api/questoes/erros/caderno", summary="Caderno de erros inteligente",
            description="Retorna questões erradas com repetição espaçada FSRS, agrupadas por padrão de erro.")
def caderno_erros(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from datetime import datetime, timedelta
    from fsrs import FSRSCard, _retrievability, STATE_NEW

    hoje = today_str()

    # Garantir que a tabela existe (com campos FSRS)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS erros_revisao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            questao_id INTEGER NOT NULL,
            resposta_id INTEGER NOT NULL,
            intervalo_atual INTEGER DEFAULT 1,
            proxima_revisao TEXT NOT NULL,
            revisoes_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT '',
            stability REAL DEFAULT NULL,
            difficulty REAL DEFAULT NULL,
            fsrs_state INTEGER DEFAULT 0,
            reps INTEGER DEFAULT 0,
            last_review TEXT DEFAULT NULL,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)

    # Buscar todos os erros do usuário
    erros = conn.execute("""
        SELECT q.id, q.materia, q.topico, q.enunciado, q.resposta_correta,
               q.alternativa_a, q.alternativa_b, q.alternativa_c, q.alternativa_d, q.alternativa_e,
               qr.resposta_usuario, qr.data, qr.id as resposta_id
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.acertou = 0 AND qr.user_id = ?
        ORDER BY qr.data DESC
    """, (user_id,)).fetchall()

    # Auto-seed erros_revisao para erros que ainda não estão na tabela
    existing_revisoes = conn.execute(
        "SELECT questao_id, resposta_id FROM erros_revisao WHERE user_id = ?", (user_id,)
    ).fetchall()
    existing_set = {(r[0], r[1]) for r in existing_revisoes}

    for erro in erros:
        key = (erro["id"], erro["resposta_id"])
        if key not in existing_set:
            # Calcular proxima_revisao: 1 dia após o erro
            try:
                data_erro = datetime.strptime(erro["data"], "%Y-%m-%d")
            except (ValueError, TypeError):
                data_erro = datetime.now()
            proxima = (data_erro + timedelta(days=1)).strftime("%Y-%m-%d")
            conn.execute("""
                INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao,
                    revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review)
                VALUES (?, ?, ?, 1, ?, 0, ?, ?, 0, 0, 0, NULL)
            """, (user_id, erro["id"], erro["resposta_id"], proxima, hoje, STATE_NEW))
            existing_set.add(key)
    conn.commit()

    # Buscar revisões com spaced repetition data (incluindo campos FSRS)
    revisoes_map = {}
    revisoes_rows = conn.execute(
        """SELECT questao_id, resposta_id, intervalo_atual, proxima_revisao, revisoes_count,
                  stability, difficulty, fsrs_state, reps, last_review
           FROM erros_revisao WHERE user_id = ?""",
        (user_id,)
    ).fetchall()
    for r in revisoes_rows:
        revisoes_map[(r["questao_id"], r["resposta_id"])] = {
            "intervalo_atual": r["intervalo_atual"],
            "proxima_revisao": r["proxima_revisao"],
            "revisoes_count": r["revisoes_count"],
            "stability": r["stability"],
            "difficulty": r["difficulty"],
            "fsrs_state": r["fsrs_state"],
            "reps": r["reps"],
            "last_review": r["last_review"],
        }

    # Montar resultado com pendentes de hoje
    pendentes_hoje = []
    todos_erros = []
    por_materia = {}
    padroes_raw = {}

    hoje_date = datetime.strptime(hoje, "%Y-%m-%d")

    for erro in erros:
        item = dict(erro)
        rev = revisoes_map.get((erro["id"], erro["resposta_id"]), {})
        item["proxima_revisao"] = rev.get("proxima_revisao", hoje)
        item["intervalo_atual"] = rev.get("intervalo_atual", 1)
        item["revisoes_count"] = rev.get("revisoes_count", 0)

        # Calcular recall_estimado via FSRS retrievability
        stability = rev.get("stability")
        last_review_str = rev.get("last_review")
        if stability and stability > 0 and last_review_str:
            try:
                last_review_date = datetime.strptime(last_review_str, "%Y-%m-%d")
                elapsed = max(0, (hoje_date - last_review_date).days)
                item["recall_estimado"] = round(_retrievability(elapsed, stability), 4)
            except (ValueError, TypeError):
                item["recall_estimado"] = 0.0
        else:
            # Card novo ou sem dados FSRS: recall = 0 (prioridade máxima)
            item["recall_estimado"] = 0.0

        todos_erros.append(item)

        # Contagem por matéria
        mat = erro["materia"] or "Sem matéria"
        por_materia[mat] = por_materia.get(mat, 0) + 1

        # Padrões de erro: agrupar por materia + topico + resposta errada
        padrao_key = f"{erro['materia']}|{erro['topico']}|{erro['resposta_usuario']}"
        if padrao_key not in padroes_raw:
            padroes_raw[padrao_key] = {
                "padrao": f"{erro['materia']} - {erro['topico'] or 'Geral'}: sempre marca '{erro['resposta_usuario']}'",
                "materia": erro["materia"],
                "topico": erro["topico"] or "Geral",
                "resposta_errada": erro["resposta_usuario"],
                "count": 0,
                "questoes": []
            }
        padroes_raw[padrao_key]["count"] += 1
        if len(padroes_raw[padrao_key]["questoes"]) < 5:
            padroes_raw[padrao_key]["questoes"].append(erro["id"])

        # Pendentes hoje: proxima_revisao <= hoje
        if item["proxima_revisao"] <= hoje:
            pendentes_hoje.append(item)

    # Ordenar pendentes por recall_estimado ASC (mais urgente primeiro)
    pendentes_hoje.sort(key=lambda x: x.get("recall_estimado", 0.0))

    # Padrões com mais de 1 ocorrência, ordenados por frequência
    padroes_erro = sorted(
        [p for p in padroes_raw.values() if p["count"] >= 2],
        key=lambda x: x["count"],
        reverse=True
    )[:20]

    return {
        "pendentes_hoje": pendentes_hoje,
        "total_erros": len(todos_erros),
        "por_materia": por_materia,
        "padroes_erro": padroes_erro,
    }


@router.post("/api/questoes/erros/revisar/{id}", summary="Revisar questão errada",
             description="Marca uma questão do caderno de erros como revisada. Usa FSRS para calcular próximo intervalo.")
def revisar_erro(id: int, body: RevisarErroRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    from datetime import datetime, timedelta
    from fsrs import (
        FSRSCard, review_card, STATE_NEW,
        RATING_AGAIN, RATING_HARD, RATING_GOOD, RATING_EASY,
    )

    DESIRED_RETENTION = 0.85  # Mais agressivo que flashcards normais (são ERROS)
    acertou = body.acertou
    hoje = today_str()

    # Determinar rating FSRS
    if not acertou:
        rating = RATING_AGAIN
    elif body.facilidade is not None:
        # facilidade 1-4 mapeia diretamente para FSRS ratings
        rating = max(1, min(4, body.facilidade))
    else:
        # Default: acertou sem facilidade = GOOD
        rating = RATING_GOOD

    # Buscar registro de revisão existente (com campos FSRS)
    revisao = conn.execute(
        """SELECT id, intervalo_atual, revisoes_count, stability, difficulty, fsrs_state, reps, last_review
           FROM erros_revisao WHERE questao_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1""",
        (id, user_id)
    ).fetchone()

    if not revisao:
        # Se não existe, verificar se a questão realmente foi errada
        erro = conn.execute(
            "SELECT id FROM questoes_respostas WHERE questao_id = ? AND acertou = 0 AND user_id = ? LIMIT 1",
            (id, user_id)
        ).fetchone()
        if not erro:
            raise HTTPException(status_code=404, detail="Questão não encontrada no caderno de erros")
        # Criar registro com FSRS state NEW
        conn.execute("""
            INSERT INTO erros_revisao (user_id, questao_id, resposta_id, intervalo_atual, proxima_revisao,
                revisoes_count, created_at, fsrs_state, stability, difficulty, reps, last_review)
            VALUES (?, ?, ?, 1, ?, 0, ?, ?, 0, 0, 0, NULL)
        """, (user_id, id, erro["id"], hoje, hoje, STATE_NEW))
        conn.commit()
        revisao = conn.execute(
            """SELECT id, intervalo_atual, revisoes_count, stability, difficulty, fsrs_state, reps, last_review
               FROM erros_revisao WHERE questao_id = ? AND user_id = ? ORDER BY id DESC LIMIT 1""",
            (id, user_id)
        ).fetchone()

    # Reconstruir FSRSCard a partir dos campos salvos
    # Retrocompatibilidade: se campos FSRS são NULL, tratar como STATE_NEW
    fsrs_state = revisao["fsrs_state"] if revisao["fsrs_state"] is not None else STATE_NEW
    stability = revisao["stability"] if revisao["stability"] is not None else 0.0
    difficulty = revisao["difficulty"] if revisao["difficulty"] is not None else 0.0
    reps = revisao["reps"] if revisao["reps"] is not None else 0
    last_review = revisao["last_review"] or ""

    card = FSRSCard(
        stability=stability,
        difficulty=difficulty,
        state=fsrs_state,
        last_review=last_review,
        reps=reps,
    )

    # Processar revisão via FSRS
    output = review_card(card, rating, desired_retention=DESIRED_RETENTION, review_date=hoje)

    # Salvar output FSRS
    conn.execute("""
        UPDATE erros_revisao
        SET intervalo_atual = ?, proxima_revisao = ?, revisoes_count = ?, updated_at = ?,
            stability = ?, difficulty = ?, fsrs_state = ?, reps = ?, last_review = ?
        WHERE id = ? AND user_id = ?
    """, (
        output.interval,
        output.next_review,
        revisao["revisoes_count"] + 1,
        hoje,
        output.stability,
        output.difficulty,
        output.state,
        reps + 1,
        hoje,
        revisao["id"],
        user_id,
    ))
    conn.commit()

    return {
        "ok": True,
        "acertou": acertou,
        "novo_intervalo": output.interval,
        "proxima_revisao": output.next_review,
        "revisoes_count": revisao["revisoes_count"] + 1,
        "stability": round(output.stability, 4),
        "difficulty": round(output.difficulty, 4),
        "recall_estimado": round(output.retrievability, 4),
    }


# Estatísticas de questões (DEVE ficar antes de /api/questoes/{id})
@router.get("/api/questoes/stats/geral", summary="Estatísticas gerais de questões",
            description="Retorna total de questões resolvidas, acertos, percentual e desempenho por matéria.")
def questoes_stats(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    total = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    por_materia = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        ORDER BY q.materia
    """, (user_id,)).fetchall()
    return {
        "total_resolvidas": total,
        "total_acertos": acertos,
        "percentual": round((acertos / total * 100) if total > 0 else 0, 1),
        "por_materia": [dict(r) for r in por_materia]
    }


@router.get("/api/questoes/stats/por-banca", summary="Estatísticas por banca examinadora",
            description="Retorna taxa de acerto agrupada por banca (CESPE, FCC, FGV, etc).")
def questoes_stats_por_banca(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna estatísticas de acerto agrupadas por banca examinadora"""
    log.info("GET /api/questoes/stats/por-banca")
    rows = conn.execute("""
        SELECT q.banca,
               COUNT(*) as total,
               SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE q.banca != '' AND q.banca IS NOT NULL AND qr.user_id = ?
        GROUP BY q.banca
        ORDER BY total DESC
    """, (user_id,)).fetchall()
    return [
        {
            "banca": r[0],
            "total": r[1],
            "acertos": r[2] or 0,
            "pct_acerto": round(((r[2] or 0) / r[1] * 100) if r[1] > 0 else 0, 1)
        }
        for r in rows
    ]


@router.get("/api/questoes/stats/tempo")
@router.get("/api/questoes/tempo-medio")
def questoes_stats_tempo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna tempo médio por questão com análise por matéria e dificuldade"""
    log.info("GET /api/questoes/stats/tempo")
    # Tempo médio geral (excluindo tempo_segundos = 0)
    geral = conn.execute("""
        SELECT AVG(tempo_segundos) as media, COUNT(*) as total
        FROM questoes_respostas
        WHERE tempo_segundos > 0 AND user_id = ?
    """, (user_id,)).fetchone()
    tempo_medio = int(geral[0]) if geral[0] else 0

    # Por matéria
    por_materia = conn.execute("""
        SELECT q.materia, AVG(qr.tempo_segundos) as media, COUNT(*) as questoes
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.tempo_segundos > 0 AND qr.user_id = ?
        GROUP BY q.materia
        ORDER BY media DESC
    """, (user_id,)).fetchall()

    # Por dificuldade
    por_dificuldade = conn.execute("""
        SELECT q.dificuldade, AVG(qr.tempo_segundos) as media
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.tempo_segundos > 0 AND qr.user_id = ?
        GROUP BY q.dificuldade
        ORDER BY media ASC
    """, (user_id,)).fetchall()

    tempo_prova_min = DEFAULT_EXAM_DURATION_MIN
    questoes_prova = DEFAULT_EXAM_QUESTIONS
    tempo_por_questao_prova = DEFAULT_TIME_PER_QUESTION_SEC

    # Análise
    if tempo_medio > 0 and tempo_medio <= tempo_por_questao_prova:
        status = "dentro_do_limite"
        mensagem = f"Seu tempo médio ({tempo_medio}s/questão) está dentro do limite da prova ({tempo_por_questao_prova}s/questão). Bom ritmo!"
    elif tempo_medio > tempo_por_questao_prova:
        status = "acima_do_limite"
        mensagem = f"Seu tempo médio ({tempo_medio}s/questão) está acima do limite da prova ({tempo_por_questao_prova}s/questão). Tente ser mais objetivo!"
    else:
        status = "sem_dados"
        mensagem = "Responda mais questões registrando o tempo para obter análise."

    # Formatar tempo
    minutos = tempo_medio // 60
    segundos = tempo_medio % 60
    tempo_formatado = f"{minutos}:{segundos:02d}"

    return {
        "tempo_medio_seg": tempo_medio,
        "tempo_medio_formatado": tempo_formatado,
        "por_materia": [
            {"materia": r[0], "tempo_medio_seg": int(r[1]), "questoes": r[2]}
            for r in por_materia
        ],
        "por_dificuldade": [
            {"dificuldade": r[0], "tempo_medio_seg": int(r[1])}
            for r in por_dificuldade
        ],
        "analise": {
            "tempo_prova_estimado_min": tempo_prova_min,
            "questoes_estimadas_prova": questoes_prova,
            "tempo_por_questao_prova_seg": tempo_por_questao_prova,
            "seu_tempo_vs_prova": status,
            "mensagem": mensagem
        }
    }


@router.get("/api/questoes/bancas")
def list_questoes_bancas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista bancas disponíveis no banco de questões"""
    log.info("GET /api/questoes/bancas")
    rows = conn.execute("SELECT DISTINCT banca FROM questoes WHERE banca != '' AND banca IS NOT NULL AND user_id = ? ORDER BY banca", (user_id,)).fetchall()
    return [r[0] for r in rows]


@router.get("/api/questoes/datas-importacao", summary="Listar datas de importação")
def list_datas_importacao(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna datas de importação com contagem de questões."""
    rows = conn.execute("""
        SELECT created_at, COUNT(*) as total,
               GROUP_CONCAT(DISTINCT materia) as materias,
               GROUP_CONCAT(DISTINCT banca) as bancas
        FROM questoes WHERE user_id = ? GROUP BY created_at ORDER BY created_at DESC
    """, (user_id,)).fetchall()
    return [{"data": r[0], "total": r[1], "materias": r[2] or "", "bancas": r[3] or ""} for r in rows]


@router.get("/api/questoes/{id}", response_model=QuestaoResponse, summary="Obter questão por ID",
            description="Retorna os dados completos de uma questão específica.",
            responses={404: {"description": "Questão não encontrada"}})
def get_questao(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    return dict(row)


@router.post("/api/questoes", summary="Criar questão", description="Adiciona uma nova questão ao banco de questões")
def create_questao(body: QuestaoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("""
        INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
            alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, created_at, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sanitize_input(body.materia), sanitize_input(body.topico),
          sanitize_input(body.enunciado, max_length=5000),
          sanitize_input(body.alternativa_a, max_length=2000),
          sanitize_input(body.alternativa_b, max_length=2000),
          sanitize_input(body.alternativa_c, max_length=2000),
          sanitize_input(body.alternativa_d, max_length=2000),
          sanitize_input(body.alternativa_e, max_length=2000),
          sanitize_input(body.resposta_correta),
          sanitize_input(body.explicacao, max_length=5000),
          sanitize_input(body.dificuldade), sanitize_input(body.banca), today_str(), user_id))
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Questão created: id={new_id} materia={body.materia}")
    return {"id": new_id, "ok": True}


@router.post("/api/questoes/{id}/responder", response_model=QuestaoRespostaResponse, summary="Responder questão", description="Registra a resposta do usuário e retorna se acertou ou errou")
def responder_questao(id: int, body: QuestaoResposta, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    questao = conn.execute("SELECT resposta_correta, materia FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
    conn.execute("""
        INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, confianca, data, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (id, body.resposta, acertou, body.tempo_segundos, body.confianca, today_str(), user_id))
    update_streak(conn, "questoes_resolvidas", user_id=user_id)

    # Registrar tempo como sessão de estudo (se > 10 segundos)
    if body.tempo_segundos > 10:
        horas = body.tempo_segundos / 3600
        materia = questao["materia"] or "Questões"
        # Acumular na sessão do dia (evitar muitas linhas)
        existing = conn.execute(
            "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND materia = ? AND tipo = 'questoes' AND user_id = ?",
            (today_str(), materia, user_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ? AND user_id = ?",
                (horas, existing["id"], user_id)
            )
        else:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'questoes', ?)",
                (materia, horas, today_str(), user_id)
            )
        # Atualizar streak de horas do dia (meta diária)
        update_streak(conn, "horas_estudadas", horas, user_id=user_id)

    conn.commit()

    # After recording the answer, update mastery for the relevant topic
    try:
        questao_full = conn.execute("SELECT materia, topico FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
        if questao_full and questao_full["topico"]:
            edital_topic = conn.execute(
                "SELECT id FROM edital WHERE (topico LIKE ? OR materia = ?) AND user_id = ? LIMIT 1",
                (f'%{questao_full["topico"]}%', questao_full["materia"], user_id)
            ).fetchone()
            if edital_topic:
                from routers.edital import _update_single_mastery
                _update_single_mastery(conn, edital_topic["id"], user_id)
                conn.commit()
    except Exception:
        pass  # Don't break question answering if mastery calc fails

    return {"acertou": bool(acertou), "resposta_correta": questao[0]}


@router.put("/api/questoes/vincular-lote", summary="Vincular disciplina em lote",
            description="Atualiza matéria/tópico/banca de todas as questões que correspondem ao filtro")
def vincular_questoes_lote(body: QuestionLinkBatch, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """
    Body: {
        filtro: {created_at?, materia_atual?, banca?},
        atualizar: {materia?, topico?, banca?, dificuldade?}
    }
    """
    filtro = body.filtro
    atualizar = body.atualizar.model_dump(exclude_unset=True)

    if not atualizar:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    # Construir WHERE
    where = "WHERE user_id = ?"
    params = [user_id]
    if filtro.created_at:
        where += " AND created_at = ?"
        params.append(filtro.created_at)
    if filtro.materia_atual:
        where += " AND materia = ?"
        params.append(filtro.materia_atual)
    elif filtro.materia_atual == "":
        where += " AND (materia IS NULL OR materia = '')"
    if filtro.banca:
        where += " AND banca = ?"
        params.append(filtro.banca)

    # Construir SET
    campos_permitidos = ["materia", "topico", "banca", "dificuldade"]
    sets = []
    for campo in campos_permitidos:
        if campo in atualizar:
            sets.append(f"{campo} = ?")
            params.append(atualizar[campo])

    if not sets:
        raise HTTPException(status_code=400, detail="Nenhum campo válido para atualizar")

    query = f"UPDATE questoes SET {', '.join(sets)} {where}"
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    log.info(f"Questões atualizadas em lote: {count} (filtro={filtro}, atualizar={atualizar})")
    return {"ok": True, "atualizadas": count}


@router.put("/api/questoes/{id}", summary="Editar questão",
            description="Atualiza campos de uma questão existente. Campos não enviados permanecem inalterados.",
            responses={404: {"description": "Questão não encontrada"}, 400: {"description": "Nenhum campo para atualizar"}})
def update_questao(id: int, body: QuestionUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Atualiza campos de uma questão (materia, topico, enunciado, alternativas, resposta, explicacao, dificuldade, banca)."""
    row = conn.execute("SELECT id FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Questão não encontrada")
    
    data = body.model_dump(exclude_unset=True)
    
    if not data:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    
    # Sanitize text fields
    text_fields = {"materia", "topico", "enunciado", "alternativa_a", "alternativa_b",
                   "alternativa_c", "alternativa_d", "alternativa_e", "resposta_correta",
                   "explicacao", "dificuldade", "banca"}
    updates = []
    params = []
    for campo, valor in data.items():
        updates.append(f"{campo} = ?")
        if campo in text_fields and isinstance(valor, str):
            max_len = 5000 if campo in ("enunciado", "explicacao") else 2000
            params.append(sanitize_input(valor, max_length=max_len))
        else:
            params.append(valor)
    
    params.append(id)
    params.append(user_id)
    conn.execute(f"UPDATE questoes SET {', '.join(updates)} WHERE id = ? AND user_id = ?", params)
    conn.commit()
    
    updated = conn.execute("SELECT * FROM questoes WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    log.info(f"Questão atualizada: id={id}")
    return dict(updated)


@router.delete("/api/questoes/{id}", summary="Excluir questão",
              description="Remove permanentemente uma questão e todas as respostas associadas.")
def delete_questao(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM questoes_respostas WHERE questao_id = ? AND user_id = ?", (id, user_id))
    conn.execute("DELETE FROM questoes WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Questão deleted: id={id}")
    return {"ok": True}


@router.get("/api/daily-challenge")
def daily_challenge(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a questão do dia (uma aleatória não respondida hoje)"""
    # Buscar questões não respondidas hoje
    respondidas_hoje = conn.execute(
        "SELECT questao_id FROM questoes_respostas WHERE data = ? AND user_id = ?", (today_str(), user_id)
    ).fetchall()
    ids_hoje = [r[0] for r in respondidas_hoje]

    if ids_hoje:
        placeholders = ','.join('?' * len(ids_hoje))
        rows = conn.execute(f"SELECT * FROM questoes WHERE user_id = ? AND id NOT IN ({placeholders})", [user_id] + ids_hoje).fetchall()
    else:
        rows = conn.execute("SELECT * FROM questoes WHERE user_id = ?", (user_id,)).fetchall()

    if not rows:
        return {"message": "Parabéns! Você já respondeu todas as questões disponíveis hoje.", "questao": None}

    chosen = random.choice(rows)
    return {"questao": dict(chosen)}


@router.get("/api/active-recall/{materia}")
def active_recall_session(materia: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera uma sessão de active recall: questões aleatórias de uma matéria"""
    rows = conn.execute("SELECT * FROM questoes WHERE materia = ? AND user_id = ?", (materia, user_id)).fetchall()
    if not rows:
        return {"questoes": [], "message": "Nenhuma questão disponível para esta matéria."}
    sample = random.sample([dict(r) for r in rows], min(5, len(rows)))
    return {"questoes": sample, "materia": materia, "total": len(sample)}


@router.get("/api/intercalacao")
def intercalacao_forcada(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Sorteia tópicos de matérias DIFERENTES para estudo intercalado"""
    materias = conn.execute("SELECT DISTINCT materia FROM edital WHERE status != 'Concluído' AND user_id = ?", (user_id,)).fetchall()
    if len(materias) < 2:
        return {"topicos": [], "message": "Precisa de pelo menos 2 matérias não concluídas."}

    selected_mats = random.sample([r[0] for r in materias], min(3, len(materias)))
    topicos = []
    for mat in selected_mats:
        rows = conn.execute(
            "SELECT id, materia, topico FROM edital WHERE materia = ? AND status != 'Concluído' AND user_id = ? ORDER BY RANDOM() LIMIT 2",
            (mat, user_id)
        ).fetchall()
        topicos.extend([dict(r) for r in rows])
    random.shuffle(topicos)
    return {"topicos": topicos, "materias": selected_mats}


@router.get("/api/questoes-vinculadas/{edital_id}")
def questoes_vinculadas(edital_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Busca questões que correspondem ao tópico de um item do edital"""
    topico = conn.execute("SELECT materia, topico FROM edital WHERE id = ? AND user_id = ?", (edital_id, user_id)).fetchone()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    rows = conn.execute("SELECT id, enunciado, resposta_correta FROM questoes WHERE materia = ? AND user_id = ? LIMIT 10",
                        (topico[0], user_id)).fetchall()
    return {"materia": topico[0], "topico": topico[1], "questoes": [dict(r) for r in rows]}


@router.get("/api/gerar-questao/{edital_id}")
def gerar_questao_template(edital_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera um template de questão baseado no tópico do edital"""
    topico = conn.execute("SELECT materia, topico FROM edital WHERE id = ? AND user_id = ?", (edital_id, user_id)).fetchone()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    return {
        "materia": topico[0],
        "topico": topico[1],
        "template": {
            "enunciado": f"Sobre {topico[1].lower()}, assinale a alternativa correta:",
            "alternativa_a": "",
            "alternativa_b": "",
            "alternativa_c": "",
            "alternativa_d": "",
            "alternativa_e": "",
            "resposta_correta": "",
            "explicacao": "",
            "dificuldade": "Médio"
        }
    }


# ==================== IMPORTAÇÃO VIA CSV ====================

def _detect_csv_format(headers: list[str]) -> str:
    """Detecta o formato do CSV baseado nos cabeçalhos das colunas."""
    headers_lower = [h.lower().strip() for h in headers]

    # QConcursos: "Disciplina", "Assunto", "Banca", "Ano", "Enunciado", "A", "B", "C", "D", "E", "Gabarito"
    qconcursos_markers = {"disciplina", "enunciado", "gabarito"}
    if qconcursos_markers.issubset(set(headers_lower)):
        return "qconcursos"

    # Gran Cursos: "Matéria", "Tópico", "Questão", "Alternativa A", ..., "Resposta", "Banca", "Ano"
    gran_markers = {"questão", "alternativa a", "resposta"}
    if gran_markers.issubset(set(headers_lower)):
        return "gran"
    # Fallback: try without accents
    gran_markers_no_accent = {"questao", "alternativa a", "resposta"}
    if gran_markers_no_accent.issubset(set(headers_lower)):
        return "gran"

    return "unknown"


def _normalize_header(h: str) -> str:
    """Normaliza header para comparação case-insensitive e sem espaços extras."""
    return h.strip().lower()


def _parse_csv_qconcursos(row: dict) -> dict:
    """Mapeia uma linha CSV no formato QConcursos para o schema da tabela questoes."""
    # Normalizar chaves do row
    norm = {_normalize_header(k): v for k, v in row.items()}

    enunciado = norm.get("enunciado", "").strip()
    if not enunciado:
        return None

    return {
        "materia": norm.get("disciplina", "").strip(),
        "topico": norm.get("assunto", "").strip(),
        "enunciado": enunciado,
        "alternativa_a": norm.get("a", "").strip(),
        "alternativa_b": norm.get("b", "").strip(),
        "alternativa_c": norm.get("c", "").strip(),
        "alternativa_d": norm.get("d", "").strip(),
        "alternativa_e": norm.get("e", "").strip(),
        "resposta_correta": norm.get("gabarito", "").strip().upper(),
        "explicacao": norm.get("explicacao", norm.get("explicação", "")).strip(),
        "dificuldade": norm.get("dificuldade", "Médio").strip() or "Médio",
        "banca": norm.get("banca", "").strip(),
        "ano": norm.get("ano", "").strip(),
    }


def _parse_csv_gran(row: dict) -> dict:
    """Mapeia uma linha CSV no formato Gran Cursos para o schema da tabela questoes."""
    norm = {_normalize_header(k): v for k, v in row.items()}

    enunciado = norm.get("questão", norm.get("questao", "")).strip()
    if not enunciado:
        return None

    return {
        "materia": norm.get("matéria", norm.get("materia", "")).strip(),
        "topico": norm.get("tópico", norm.get("topico", "")).strip(),
        "enunciado": enunciado,
        "alternativa_a": norm.get("alternativa a", "").strip(),
        "alternativa_b": norm.get("alternativa b", "").strip(),
        "alternativa_c": norm.get("alternativa c", "").strip(),
        "alternativa_d": norm.get("alternativa d", "").strip(),
        "alternativa_e": norm.get("alternativa e", "").strip(),
        "resposta_correta": norm.get("resposta", "").strip().upper(),
        "explicacao": norm.get("explicacao", norm.get("explicação", "")).strip(),
        "dificuldade": norm.get("dificuldade", "Médio").strip() or "Médio",
        "banca": norm.get("banca", "").strip(),
        "ano": norm.get("ano", "").strip(),
    }


def _decode_csv_content(raw_bytes: bytes) -> str:
    """Decodifica conteúdo CSV tratando UTF-8 BOM e fallback para latin1."""
    # Tentar UTF-8 com BOM
    try:
        if raw_bytes.startswith(codecs.BOM_UTF8):
            return raw_bytes.decode("utf-8-sig")
        return raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # Fallback: latin1 (ISO-8859-1)
    try:
        return raw_bytes.decode("latin-1")
    except UnicodeDecodeError:
        # Último recurso: ignorar erros
        return raw_bytes.decode("utf-8", errors="replace")


@router.post("/api/questoes/importar-csv", summary="Importar questões via CSV",
             description="Importa questões de CSVs exportados do QConcursos ou Gran Cursos")
async def importar_csv(
    file: UploadFile = File(...),
    formato: str = Query("auto", description="Formato: auto, qconcursos, gran"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """
    Aceita um arquivo CSV com questões de múltipla escolha.
    
    Formatos suportados:
    - **QConcursos**: Disciplina, Assunto, Banca, Ano, Enunciado, A, B, C, D, E, Gabarito
    - **Gran Cursos**: Matéria, Tópico, Questão, Alternativa A-E, Resposta, Banca, Ano
    
    Detecção automática pelo cabeçalho. Limite: 5000 linhas por importação.
    """
    if not file.filename or not file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail="Apenas arquivos CSV são aceitos.")

    # Ler conteúdo
    raw_bytes = await file.read()
    if not raw_bytes:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")

    # Decodificar
    text_content = _decode_csv_content(raw_bytes)

    # Detectar delimitador (vírgula ou ponto-e-vírgula)
    first_line = text_content.split('\n', 1)[0]
    delimiter = ';' if first_line.count(';') > first_line.count(',') else ','

    # Parsear CSV
    reader = csv.DictReader(io.StringIO(text_content), delimiter=delimiter)

    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="CSV sem cabeçalho válido.")

    # Detectar formato
    detected_format = formato
    if formato == "auto":
        detected_format = _detect_csv_format(reader.fieldnames)
        if detected_format == "unknown":
            raise HTTPException(
                status_code=400,
                detail=f"Formato não reconhecido. Cabeçalhos encontrados: {', '.join(reader.fieldnames)}. "
                       f"Use formato=qconcursos ou formato=gran explicitamente."
            )

    # Selecionar parser
    if detected_format == "qconcursos":
        parse_row = _parse_csv_qconcursos
    elif detected_format == "gran":
        parse_row = _parse_csv_gran
    else:
        raise HTTPException(status_code=400, detail=f"Formato inválido: {formato}. Use: auto, qconcursos, gran.")

    # Processar linhas
    imported = 0
    duplicates = 0
    errors = []
    row_num = 0
    MAX_ROWS = 5000

    for row in reader:
        row_num += 1
        if row_num > MAX_ROWS:
            errors.append(f"Limite de {MAX_ROWS} linhas atingido. Linhas restantes ignoradas.")
            break

        try:
            questao = parse_row(row)
            if questao is None:
                errors.append(f"Linha {row_num + 1}: enunciado vazio, ignorada.")
                continue

            # Validar campos mínimos
            if len(questao["enunciado"]) < 10:
                errors.append(f"Linha {row_num + 1}: enunciado muito curto ({len(questao['enunciado'])} chars).")
                continue

            # Verificar duplicata (mesmo enunciado + banca + ano)
            existing = conn.execute(
                "SELECT id FROM questoes WHERE user_id = ? AND enunciado = ? AND banca = ? AND created_at LIKE ?",
                (user_id, questao["enunciado"], questao["banca"],
                 f"%{questao.get('ano', '')}%" if questao.get("ano") else "%")
            ).fetchone()

            if existing:
                duplicates += 1
                continue

            # Inserir
            conn.execute("""
                INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                    alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao,
                    dificuldade, banca, ano, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                questao["materia"],
                questao["topico"],
                questao["enunciado"],
                questao["alternativa_a"],
                questao["alternativa_b"],
                questao["alternativa_c"],
                questao["alternativa_d"],
                questao["alternativa_e"],
                questao["resposta_correta"],
                questao.get("explicacao", ""),
                questao["dificuldade"],
                questao["banca"],
                questao.get("ano", ""),
                today_str(),
                user_id,
            ))
            imported += 1

        except Exception as e:
            errors.append(f"Linha {row_num + 1}: {str(e)}")

    conn.commit()
    log.info(f"CSV import: {imported} questões importadas de {file.filename} (formato={detected_format}, duplicatas={duplicates})")

    return {
        "imported": imported,
        "duplicates": duplicates,
        "errors": errors[:50],  # Limitar erros retornados
        "format_detected": detected_format,
        "total_rows": row_num,
    }


# ==================== IMPORTAÇÃO VIA PDF (OCR) ====================

def _extrair_texto_pdf(file_path: str) -> str:
    """Extrai texto do PDF: primeiro tenta pypdf (texto digital), depois OCR se necessário."""
    from pypdf import PdfReader

    reader = PdfReader(file_path)
    texto = ""
    for page in reader.pages:
        page_text = page.extract_text() or ""
        texto += page_text + "\n"

    # Se o texto extraído é muito curto, provavelmente é PDF escaneado — usar OCR
    if len(texto.strip()) < 100:
        try:
            from pdf2image import convert_from_path
            import pytesseract

            log.info("PDF sem texto selecionável, usando OCR...")
            images = convert_from_path(file_path, dpi=300)
            texto = ""
            for img in images:
                texto += pytesseract.image_to_string(img, lang='por') + "\n"
        except ImportError:
            log.warning("pytesseract/pdf2image não instalados. Instale com: pip install pytesseract pdf2image")
            raise
        except Exception as e:
            log.error(f"Erro no OCR: {e}")
            raise

    return texto


def _parse_gabarito(texto: str) -> dict:
    """Extrai gabarito do texto. Busca padrões como '1-A', '1.A', '1) A', 'Q1: A', etc."""
    gabarito = {}

    # Padrões comuns de gabarito
    patterns = [
        r'(\d+)\s*[-–.):]\s*([A-Ea-e])',           # 1-A, 1.A, 1)A, 1: A
        r'[Qq](?:uestão)?\s*(\d+)\s*[-–.):]\s*([A-Ea-e])',  # Q1: A, Questão 1: A
        r'(\d+)\s*\|\s*([A-Ea-e])',                 # 1 | A
    ]

    for pattern in patterns:
        matches = re.findall(pattern, texto)
        if matches:
            for num, letra in matches:
                gabarito[int(num)] = letra.upper()
            if len(gabarito) >= 3:
                break

    return gabarito


def _parse_qconcursos(texto: str, materia_override: str = "") -> list:
    """
    Parser para formato QConcursos:
    Ano: 2026Banca: FUNDATECÓrgão: Polícia Penal - RS
    [enunciado]
    A [texto alternativa A]
    B [texto alternativa B]
    ...
    
    Gabarito no final: "Respostas\n1:B 2:D 3:B..."
    """
    questoes = []

    # 1. Extrair gabarito do final (formato "1:B 2:D 3:B" ou "1:B\n2:D\n3:B")
    gabarito = {}
    gab_match = re.search(r'(?:Respostas|Gabarito|GABARITO)\s*\n(.+?)(?:www\.|$)', texto, re.DOTALL | re.IGNORECASE)
    if gab_match:
        gab_text = gab_match.group(1)
        # Padrão "1:B" ou "1: B"
        gab_entries = re.findall(r'(\d+)\s*:\s*([A-Ea-e])', gab_text)
        for num, letra in gab_entries:
            gabarito[int(num)] = letra.upper()
    
    # Remover seção de gabarito e metadados finais do texto de questões
    texto_limpo = texto
    # Remover bloco "18 Q4228074 >Direito..." (índice de questões no final)
    texto_limpo = re.sub(r'\d+\s+Q\d+\s+>.*?(?=Ano:\s*\d{4}|Respostas|$)', '', texto_limpo, flags=re.DOTALL)
    # Remover seção de respostas
    texto_limpo = re.sub(r'(?:Respostas|Gabarito)\s*\n.*$', '', texto_limpo, flags=re.DOTALL | re.IGNORECASE)
    # Remover header do site
    texto_limpo = re.sub(r'www\.qconcursos\.com\s*\n?', '', texto_limpo)

    # 2. Separar questões pelo padrão "Ano: XXXX"
    header_pattern = r'Ano:\s*(\d{4})\s*Banca:\s*(.+?)(?:Órgão|Orgão|Prova):\s*(.+?)(?=\n|$)'
    
    # Dividir o texto em blocos de questões usando o header como separador
    splits = re.split(r'(?=Ano:\s*\d{4}\s*Banca:)', texto_limpo)
    
    # Determinar numeração base do gabarito (ex: se começa em 21, offset = 21)
    gab_start = min(gabarito.keys()) if gabarito else 1
    quest_num = gab_start - 1  # será incrementado para gab_start na primeira questão
    for bloco in splits:
        bloco = bloco.strip()
        if not bloco or len(bloco) < 30:
            continue
        
        # Extrair metadados do header
        header_match = re.match(header_pattern, bloco, re.IGNORECASE)
        if not header_match:
            continue
        
        quest_num += 1
        ano = header_match.group(1)
        banca_q = header_match.group(2).strip().rstrip('Óó')
        orgao = header_match.group(3).strip()
        
        # Limpar banca (pode ter "Órgão" colado)
        banca_q = re.sub(r'[ÓO]rg[ãa]o.*$', '', banca_q, flags=re.IGNORECASE).strip()
        
        # Texto após o header = enunciado + alternativas
        corpo = bloco[header_match.end():].strip()
        
        if len(corpo) < 20:
            continue
        
        # Encontrar alternativas
        # Formato QConcursos: letra seguida de espaço no início de linha
        alt_pattern = r'(?:^|\n)\s*([A-E])\s+(.+?)(?=(?:^|\n)\s*[A-E]\s+|\Z)'
        alt_matches = re.findall(alt_pattern, corpo, re.DOTALL)
        
        if len(alt_matches) < 4:
            # Tentar variação: letra seguida de espaço (mais agressivo)
            alt_pattern2 = r'(?:^|\n)([A-E])\s{1,3}(.+?)(?=(?:^|\n)[A-E]\s{1,3}|\Z)'
            alt_matches = re.findall(alt_pattern2, corpo, re.DOTALL)
        
        if len(alt_matches) < 4:
            continue
        
        # Encontrar onde começa a primeira alternativa para separar o enunciado
        first_alt_re = re.search(r'(?:^|\n)\s*A\s+', corpo, re.MULTILINE)
        if first_alt_re:
            enunciado = corpo[:first_alt_re.start()].strip()
        else:
            enunciado = corpo.split('\n')[0].strip()
        
        # Limpar enunciado (remover quebras de linha internas)
        enunciado = re.sub(r'\s*\n\s*', ' ', enunciado).strip()
        
        if len(enunciado) < 15:
            continue
        
        # Montar alternativas
        alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
        for letra, texto_alt in alt_matches[:5]:
            # Limpar texto da alternativa (remover quebras internas)
            clean_text = re.sub(r'\s*\n\s*', ' ', texto_alt).strip()
            alts[letra.upper()] = clean_text
        
        # Buscar resposta no gabarito
        resposta = gabarito.get(quest_num, '')
        
        questao = {
            "numero": quest_num,
            "materia": materia_override or "",
            "topico": "",
            "enunciado": enunciado,
            "alternativa_a": alts['A'],
            "alternativa_b": alts['B'],
            "alternativa_c": alts['C'],
            "alternativa_d": alts['D'],
            "alternativa_e": alts['E'],
            "resposta_correta": resposta,
            "explicacao": "",
            "dificuldade": "Médio",
            "banca": banca_q,
        }
        questoes.append(questao)
    
    return questoes


def _is_cespe_format(texto: str) -> bool:
    """Detecta se o PDF é formato CESPE/Cebraspe (itens Certo/Errado)."""
    indicators = [
        r'(?i)cebraspe',
        r'(?i)cespe',
        r'(?i)julgue\s+o[s]?\s+(?:seguinte|próximo|item|iten)',
        r'(?i)marque.*?campo.*?(?:C|CERTO).*?(?:E|ERRADO)',
        r'(?i)item.*?CERTO.*?ERRADO',
    ]
    score = sum(1 for p in indicators if re.search(p, texto[:3000]))
    # Also check: numbered items without A-E alternatives
    items_numbered = len(re.findall(r'\n\s*\d{1,3}\s+[A-Z]', texto[:5000]))
    alternatives = len(re.findall(r'\n\s*\(?[A-E]\)', texto[:5000]))
    # CESPE: many numbered items, few/no A-E alternatives
    if score >= 2 or (items_numbered > 5 and alternatives < 3):
        return True
    return False


def _parse_cespe_cebraspe(texto: str, materia: str = "", banca: str = "CESPE") -> list:
    """
    Parser para provas CESPE/Cebraspe (formato Certo/Errado).
    
    Formato típico:
    - Texto motivador (pode ser longo)
    - "Julgue os itens a seguir..." ou "Com base no texto, julgue..."
    - Itens numerados: "14 O termo 'sábio'..."
    - Sem alternativas A-E (cada item é C ou E)
    
    Também suporta FCC/FGV com alternativas A-E detectadas por bloco.
    """
    questoes = []
    
    # Detectar matérias/tópicos pelos cabeçalhos do texto
    # CESPE usa seções: "-- CONHECIMENTOS GERAIS --" e blocos "Julgue os itens... referentes a [MATÉRIA]"
    section_headers = re.findall(r'--\s*(.+?)\s*--', texto)
    
    # Detectar temas por "Julgue/considere... referentes a / sobre / de acordo com"
    tema_patterns = re.findall(
        r'(?i)(?:julgue|considere|com\s+base|a\s+respeito|acerca).*?(?:referentes?\s+a[o]?|sobre|relativos?\s+a[o]?|de\s+acordo\s+com\s+o\s+disposto\s+n[ao]?)\s+(.+?)(?:\.|,\s*julgue)',
        texto
    )
    # Also: "Com base nas Resoluções X, julgue..." or "Acerca de [tema], julgue"
    tema_acerca = re.findall(
        r'(?i)(?:acerca\s+d[eoa]s?|(?:no|com)\s+(?:que|base).*?(?:refere|concerne).*?a[o]?)\s+(.+?)(?:,\s*julgue|\.\s*\n)',
        texto
    )
    materias_blocos = [(texto.find(t), t.strip()[:80]) for t in tema_patterns + tema_acerca if len(t.strip()) > 5]
    materias_blocos.sort(key=lambda x: x[0])
    
    # Extrair gabarito se existir no PDF (CESPE geralmente tem gabarito separado)
    gabarito = {}
    gab_section = ""
    for marker in ['GABARITO', 'Gabarito Oficial', 'GABARITO OFICIAL']:
        pos = texto.rfind(marker)
        if pos > 0:
            gab_section = texto[pos:]
            break
    
    if gab_section:
        # Padrão: "1 C 2 E 3 C" ou "1-C 2-E" ou "1. C  2. E"
        gab_matches = re.findall(r'(\d{1,3})\s*[.\-–):]?\s*([CEce])', gab_section)
        for num, resp in gab_matches:
            gabarito[int(num)] = resp.upper()
    
    # Encontrar itens numerados (padrão CESPE: número seguido de espaço e texto)
    # Padrão: "14 O termo 'sábio'..." no início de linha
    item_pattern = r'(?:^|\n)\s*(\d{1,3})\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][^\n]{15,})'
    
    items = list(re.finditer(item_pattern, texto))
    
    if not items:
        # Tentar padrão alternativo: número com ponto
        item_pattern = r'(?:^|\n)\s*(\d{1,3})\.\s+([A-ZÁÀÂÃÉÊÍÓÔÕÚÇ][^\n]{15,})'
        items = list(re.finditer(item_pattern, texto))
    
    # Para cada item, extrair o texto completo até o próximo item
    for i, match in enumerate(items):
        num = int(match.group(1))
        
        # Pegar texto até o próximo item
        start = match.start() + len(match.group(0).split('\n')[0]) + 1 if '\n' in match.group(0) else match.end()
        start = match.start()
        end = items[i + 1].start() if i + 1 < len(items) else len(texto)
        
        bloco = texto[match.start():end].strip()
        
        # Remover número do início
        enunciado = re.sub(r'^\d{1,3}\s+', '', bloco).strip()
        
        # Limpar quebras de linha internas (manter como texto contínuo)
        enunciado = re.sub(r'\s*\n\s*', ' ', enunciado).strip()
        
        # Verificar se tem alternativas A-E (pode ser FCC misturado no mesmo PDF)
        alt_match = re.findall(r'\(?([A-E])\)?\s*(.+?)(?=\(?[A-E]\)|$)', enunciado)
        
        if len(alt_match) >= 4:
            # Formato múltipla escolha dentro do item
            # Separar enunciado das alternativas
            first_alt = re.search(r'\(?A\)?\s', enunciado)
            if first_alt:
                texto_enunciado = enunciado[:first_alt.start()].strip()
                alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
                for letra, txt in alt_match[:5]:
                    alts[letra] = txt.strip()
                
                resposta = gabarito.get(num, "")
                questoes.append({
                    "numero": num,
                    "enunciado": texto_enunciado,
                    "alternativa_a": alts['A'],
                    "alternativa_b": alts['B'],
                    "alternativa_c": alts['C'],
                    "alternativa_d": alts['D'],
                    "alternativa_e": alts['E'],
                    "resposta_correta": resposta,
                    "materia": materia,
                    "topico": "",
                    "explicacao": "",
                    "dificuldade": "Médio",
                    "banca": banca,
                    "tipo": "multipla_escolha",
                })
        else:
            # Formato CESPE Certo/Errado (sem alternativas)
            # Limitar tamanho do enunciado (pode ter capturado texto demais)
            if len(enunciado) > 800:
                enunciado = enunciado[:800].strip()
            
            # Verificar se é um item válido (não é cabeçalho ou instrução)
            if len(enunciado) < 30:
                continue
            if re.match(r'(?i)^(julgue|considere|com base|acerca|espaço livre|provas objetivas)', enunciado):
                continue
            
            resposta = gabarito.get(num, "")
            
            # Tentar detectar matéria pelo contexto (bloco anterior mais próximo)
            item_materia = materia
            if not item_materia and materias_blocos:
                # Usar a matéria do bloco mais recente antes deste item
                for pos, tema in reversed(materias_blocos):
                    if pos < match.start():
                        item_materia = tema
                        break
            
            questoes.append({
                "numero": num,
                "enunciado": enunciado,
                "alternativa_a": "CERTO",
                "alternativa_b": "ERRADO",
                "alternativa_c": "",
                "alternativa_d": "",
                "alternativa_e": "",
                "resposta_correta": resposta if resposta in ('C', 'E') else "",
                "materia": item_materia or "Conhecimentos Gerais",
                "topico": "",
                "explicacao": "",
                "dificuldade": "Médio",
                "banca": banca,
                "tipo": "certo_errado",
            })
    
    # Mapear resposta C/E para A/B (compatibilidade com o banco)
    for q in questoes:
        if q["tipo"] == "certo_errado":
            if q["resposta_correta"] == "C":
                q["resposta_correta"] = "A"  # A = CERTO
            elif q["resposta_correta"] == "E":
                q["resposta_correta"] = "B"  # B = ERRADO
    
    return questoes


def _parse_questoes_texto(texto: str, materia: str = "", banca: str = "") -> list:
    """Analisa texto extraído e separa em questões individuais."""
    questoes = []

    # Detectar formato QConcursos (Ano: XXXX Banca: XXX Órgão: XXX)
    if re.search(r'Ano:\s*\d{4}\s*Banca:', texto):
        return _parse_qconcursos(texto, materia_override=materia)

    # Detectar formato CESPE/Cebraspe (itens Certo/Errado)
    if _is_cespe_format(texto):
        return _parse_cespe_cebraspe(texto, materia=materia, banca=banca or "CESPE")

    # Separar seção de questões da seção de gabarito
    # Identificar onde começa o gabarito
    gab_markers = ['GABARITO', 'Gabarito', 'RESPOSTAS', 'Respostas', 'CARTÃO RESPOSTA']
    texto_questoes = texto
    texto_gabarito = ""

    for marker in gab_markers:
        pos = texto.rfind(marker)
        if pos > 0:
            texto_questoes = texto[:pos]
            texto_gabarito = texto[pos:]
            break

    # Extrair gabarito
    gabarito = _parse_gabarito(texto_gabarito if texto_gabarito else texto)

    # Padrões para identificar início de questão
    quest_patterns = [
        r'(?:^|\n)\s*(?:QUESTÃO|Questão|questão)\s+(\d+)',
        r'(?:^|\n)\s*(\d+)\s*[.)]\s+(?=[A-Z])',      # "1. " ou "1) " seguido de letra maiúscula
        r'(?:^|\n)\s*(\d+)\s*[-–]\s+',                # "1 - "
    ]

    # Encontrar posições de início de cada questão
    quest_positions = []
    for pattern in quest_patterns:
        for m in re.finditer(pattern, texto_questoes):
            quest_positions.append((m.start(), int(m.group(1)), m.end()))
        if quest_positions:
            break

    # Ordenar por posição
    quest_positions.sort(key=lambda x: x[0])

    # Extrair texto de cada questão
    for i, (start, num, text_start) in enumerate(quest_positions):
        # Fim é o início da próxima questão ou fim do texto
        end = quest_positions[i + 1][0] if i + 1 < len(quest_positions) else len(texto_questoes)
        bloco = texto_questoes[text_start:end].strip()

        if len(bloco) < 20:
            continue

        # Separar enunciado e alternativas
        alt_pattern = r'\n\s*\(?([A-Ea-e])\)?\s*[-–.]?\s*(.+?)(?=\n\s*\(?[A-Ea-e]\)|\Z)'
        alternativas_matches = re.findall(alt_pattern, bloco, re.DOTALL)

        if len(alternativas_matches) < 4:
            # Tentar outro padrão
            alt_pattern2 = r'(?:^|\n)\s*([A-Ea-e])\s*[).\-–]\s*(.+?)(?=(?:^|\n)\s*[A-Ea-e]\s*[).\-–]|\Z)'
            alternativas_matches = re.findall(alt_pattern2, bloco, re.DOTALL)

        if len(alternativas_matches) < 4:
            continue

        # Encontrar onde começa a primeira alternativa para separar enunciado
        first_alt_pos = bloco.find(alternativas_matches[0][1].strip()[:20])
        if first_alt_pos > 0:
            # Voltar até a letra da alternativa
            search_back = bloco[:first_alt_pos].rfind(alternativas_matches[0][0])
            enunciado = bloco[:search_back].strip() if search_back > 0 else bloco[:first_alt_pos].strip()
        else:
            enunciado = bloco.split('\n')[0].strip()

        # Limpar enunciado
        enunciado = re.sub(r'^\d+\s*[.):\-–]\s*', '', enunciado).strip()

        # Montar alternativas
        alts = {'A': '', 'B': '', 'C': '', 'D': '', 'E': ''}
        for letra, texto_alt in alternativas_matches[:5]:
            alts[letra.upper()] = texto_alt.strip()

        # Buscar resposta no gabarito
        resposta = gabarito.get(num, '')

        questao = {
            "numero": num,
            "materia": materia,
            "topico": "",
            "enunciado": enunciado,
            "alternativa_a": alts['A'],
            "alternativa_b": alts['B'],
            "alternativa_c": alts['C'],
            "alternativa_d": alts['D'],
            "alternativa_e": alts['E'],
            "resposta_correta": resposta,
            "explicacao": "",
            "dificuldade": "Médio",
            "banca": banca,
        }
        questoes.append(questao)

    return questoes


@router.post("/api/questoes/importar-pdf",
             summary="Importar questões de PDF",
             description="Extrai questões de um PDF (com texto ou escaneado via OCR) e cadastra no banco")
async def importar_questoes_pdf(
    file: UploadFile = File(...),
    gabarito_file: UploadFile = File(None),
    materia: str = "",
    banca: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """
    Aceita PDF com questões + opcionalmente PDF de gabarito separado.
    - Extrai texto via pypdf (PDF digital) ou pytesseract (PDF escaneado/OCR)
    - Identifica questões numeradas com alternativas A-E ou itens C/E (CESPE)
    - Busca gabarito no mesmo PDF ou no PDF de gabarito enviado separadamente
    """
    if not file.filename.endswith('.pdf'):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    # Salvar arquivo temporário da prova
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name

    # Se enviou gabarito separado, extrair respostas dele
    gabarito_externo = {}
    if gabarito_file and gabarito_file.filename:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp_gab:
            gab_content = await gabarito_file.read()
            tmp_gab.write(gab_content)
            tmp_gab_path = tmp_gab.name
        try:
            gab_texto = _extrair_texto_pdf(tmp_gab_path)
            gabarito_externo = _parse_gabarito(gab_texto)
            if not gabarito_externo:
                # Tentar padrão CESPE: grid de números e letras C/E
                import re
                matches = re.findall(r'(\d{1,3})\s*[.\-–):]?\s*([A-Ea-eCcEeXx])', gab_texto)
                for num, resp in matches:
                    r = resp.upper()
                    if r == 'X':
                        continue  # anulada
                    gabarito_externo[int(num)] = r
        except Exception:
            pass
        finally:
            import os
            os.unlink(tmp_gab_path)

    try:
        # Extrair texto da prova
        texto = _extrair_texto_pdf(tmp_path)

        if len(texto.strip()) < 50:
            raise HTTPException(status_code=400, detail="Não foi possível extrair texto do PDF. Verifique se o arquivo contém questões legíveis.")

        # Parsear questões
        questoes = _parse_questoes_texto(texto, materia=materia, banca=banca)

        # Aplicar gabarito externo se fornecido
        if gabarito_externo and questoes:
            for q in questoes:
                num = q.get("numero", 0)
                if num in gabarito_externo and not q.get("resposta_correta"):
                    gab = gabarito_externo[num]
                    if gab in ('C', 'E') and q.get("tipo") == "certo_errado":
                        q["resposta_correta"] = "A" if gab == "C" else "B"
                    elif gab in ('A', 'B', 'C', 'D', 'E'):
                        q["resposta_correta"] = gab

        if not questoes:
            # Retornar o texto extraído para debug
            return {
                "ok": False,
                "importadas": 0,
                "erro": "Não foi possível identificar questões no formato esperado.",
                "texto_extraido_preview": texto[:2000],
                "dica": "O PDF deve conter questões numeradas (1, 2, 3...) com alternativas (A, B, C, D, E) e preferencialmente uma seção de GABARITO."
            }

        # Inserir no banco
        count = 0
        sem_gabarito = 0
        for q in questoes:
            if not q["enunciado"] or len(q["enunciado"]) < 10:
                continue
            if not q["resposta_correta"]:
                sem_gabarito += 1
            conn.execute("""
                INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                    alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, banca, created_at, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (q["materia"], q["topico"], q["enunciado"], q["alternativa_a"], q["alternativa_b"],
                  q["alternativa_c"], q["alternativa_d"], q["alternativa_e"], q["resposta_correta"],
                  q["explicacao"], q["dificuldade"], q["banca"], today_str(), user_id))
            count += 1

        conn.commit()
        log.info(f"PDF import: {count} questões importadas de {file.filename}")

        return {
            "ok": True,
            "importadas": count,
            "sem_gabarito": sem_gabarito,
            "total_detectadas": len(questoes),
            "mensagem": f"{count} questões importadas com sucesso!" + (f" ({sem_gabarito} sem gabarito identificado)" if sem_gabarito else "")
        }

    except HTTPException:
        raise
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="OCR não disponível. Instale: pip install pytesseract pdf2image. E instale o Tesseract: sudo apt install tesseract-ocr tesseract-ocr-por"
        ) from None
    except Exception as e:
        log.error(f"Erro ao importar PDF: {e}")
        raise HTTPException(status_code=500, detail=f"Erro ao processar PDF: {str(e)}") from None
    finally:
        import os
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

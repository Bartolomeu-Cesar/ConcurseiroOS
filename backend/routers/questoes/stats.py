"""Estatísticas de questões: stats gerais, por banca, tempo, listagens de bancas/provas/datas."""
from fastapi import APIRouter, Depends, HTTPException

from constants import DEFAULT_EXAM_DURATION_MIN, DEFAULT_EXAM_QUESTIONS, DEFAULT_TIME_PER_QUESTION_SEC
from database import get_db_session
from deps import get_user_id
from logger import log

router = APIRouter()


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
    geral = conn.execute("""
        SELECT AVG(tempo_segundos) as media, COUNT(*) as total
        FROM questoes_respostas
        WHERE tempo_segundos > 0 AND user_id = ?
    """, (user_id,)).fetchone()
    tempo_medio = int(geral[0]) if geral[0] else 0

    por_materia = conn.execute("""
        SELECT q.materia, AVG(qr.tempo_segundos) as media, COUNT(*) as questoes
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.tempo_segundos > 0 AND qr.user_id = ?
        GROUP BY q.materia
        ORDER BY media DESC
    """, (user_id,)).fetchall()

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

    if tempo_medio > 0 and tempo_medio <= tempo_por_questao_prova:
        status = "dentro_do_limite"
        mensagem = f"Seu tempo médio ({tempo_medio}s/questão) está dentro do limite da prova ({tempo_por_questao_prova}s/questão). Bom ritmo!"
    elif tempo_medio > tempo_por_questao_prova:
        status = "acima_do_limite"
        mensagem = f"Seu tempo médio ({tempo_medio}s/questão) está acima do limite da prova ({tempo_por_questao_prova}s/questão). Tente ser mais objetivo!"
    else:
        status = "sem_dados"
        mensagem = "Responda mais questões registrando o tempo para obter análise."

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


@router.get("/api/questoes/provas", summary="Listar provas importadas")
def listar_provas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna lista de provas importadas com contagem de questões e status do gabarito."""
    rows = conn.execute("""
        SELECT prova_origem,
               COUNT(*) as total,
               SUM(CASE WHEN resposta_correta != '' AND resposta_correta IS NOT NULL THEN 1 ELSE 0 END) as com_gabarito,
               banca,
               MIN(created_at) as importada_em
        FROM questoes
        WHERE user_id = ? AND prova_origem != ''
        GROUP BY prova_origem
        ORDER BY MAX(id) DESC
    """, (user_id,)).fetchall()

    result = []
    for r in rows:
        mat_row = conn.execute("""
            SELECT materia, COUNT(*) as cnt FROM questoes
            WHERE user_id = ? AND prova_origem = ? AND materia != '' AND materia IS NOT NULL
            GROUP BY materia ORDER BY cnt DESC LIMIT 1
        """, (user_id, r[0])).fetchone()
        materia = mat_row[0] if mat_row else ""

        result.append({
            "prova": r[0],
            "total_questoes": r[1],
            "com_gabarito": r[2],
            "sem_gabarito": r[1] - r[2],
            "banca": r[3],
            "importada_em": r[4],
            "gabarito_completo": r[2] == r[1],
            "materia": materia,
        })

    return result


@router.delete("/api/questoes/provas/{prova_nome}", summary="Excluir prova inteira",
               description="Remove todas as questões e respostas associadas a uma prova importada.")
def excluir_prova(prova_nome: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Exclui todas as questões de uma prova específica (por prova_origem)."""
    from urllib.parse import unquote
    prova_nome = unquote(prova_nome)

    count = conn.execute(
        "SELECT COUNT(*) FROM questoes WHERE user_id = ? AND prova_origem = ?",
        (user_id, prova_nome)
    ).fetchone()[0]

    if count == 0:
        raise HTTPException(status_code=404, detail=f"Prova '{prova_nome}' não encontrada.")

    conn.execute("""
        DELETE FROM questoes_respostas
        WHERE user_id = ? AND questao_id IN (
            SELECT id FROM questoes WHERE user_id = ? AND prova_origem = ?
        )
    """, (user_id, user_id, prova_nome))

    conn.execute("""
        DELETE FROM erros_revisao
        WHERE user_id = ? AND questao_id IN (
            SELECT id FROM questoes WHERE user_id = ? AND prova_origem = ?
        )
    """, (user_id, user_id, prova_nome))

    conn.execute(
        "DELETE FROM questoes WHERE user_id = ? AND prova_origem = ?",
        (user_id, prova_nome)
    )

    conn.commit()
    log.info(f"Prova excluída: '{prova_nome}' ({count} questões) por user_id={user_id}")

    return {"ok": True, "excluidas": count, "mensagem": f"Prova '{prova_nome}' excluída ({count} questões removidas)."}

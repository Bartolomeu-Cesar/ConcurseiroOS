import random
import math
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from database import get_db
from logger import log
from models import QuestaoCreate, QuestaoResposta
from utils import today_str

router = APIRouter(prefix="", tags=["Questões"])


@router.get("/api/questoes", summary="Listar questões", description="Lista todas as questões do banco, com filtros por matéria/tópico e paginação opcional")
def list_questoes(
    materia: str = "",
    topico: str = "",
    dificuldade: str = "",
    acertou: Optional[int] = Query(None),
    respondidas: Optional[int] = Query(None),
    data_inicio: str = "",
    data_fim: str = "",
    page: Optional[int] = Query(None),
    limit: int = 50
):
    with get_db() as conn:
        params = []

        # Determinar tipo de query baseado nos filtros
        needs_join = acertou is not None or data_inicio or data_fim
        needs_not_in = respondidas == 0

        if needs_not_in:
            # Questões NÃO respondidas
            query = "SELECT q.* FROM questoes q WHERE q.id NOT IN (SELECT questao_id FROM questoes_respostas)"
            if materia:
                query += " AND q.materia = ?"
                params.append(materia)
            if topico:
                query += " AND q.topico = ?"
                params.append(topico)
            if dificuldade:
                query += " AND q.dificuldade = ?"
                params.append(dificuldade)
        elif needs_join or respondidas == 1:
            # Questões com filtro por respostas (acertou/errou, datas)
            query = "SELECT DISTINCT q.* FROM questoes q JOIN questoes_respostas qr ON qr.questao_id = q.id WHERE 1=1"
            if materia:
                query += " AND q.materia = ?"
                params.append(materia)
            if topico:
                query += " AND q.topico = ?"
                params.append(topico)
            if dificuldade:
                query += " AND q.dificuldade = ?"
                params.append(dificuldade)
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
            query = "SELECT * FROM questoes WHERE 1=1"
            if materia:
                query += " AND materia = ?"
                params.append(materia)
            if topico:
                query += " AND topico = ?"
                params.append(topico)
            if dificuldade:
                query += " AND dificuldade = ?"
                params.append(dificuldade)

        query += " ORDER BY q.id DESC" if (needs_join or needs_not_in or respondidas == 1) else " ORDER BY id DESC"
        rows = conn.execute(query, params).fetchall()

    items = [dict(r) for r in rows]

    # Se page não fornecido, retorna array completo (retrocompatibilidade)
    if page is None:
        return items

    # Paginação
    total = len(items)
    pages = math.ceil(total / limit) if limit > 0 else 1
    start = (page - 1) * limit
    end = start + limit
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages
    }


@router.get("/api/questoes/materias")
def list_questoes_materias():
    with get_db() as conn:
        rows = conn.execute("SELECT DISTINCT materia FROM questoes ORDER BY materia").fetchall()
    return [r[0] for r in rows]


# Caderno de Erros (DEVE ficar antes de /api/questoes/{id})
@router.get("/api/questoes/erros/caderno")
def caderno_erros():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT q.id, q.materia, q.topico, q.enunciado, q.resposta_correta, qr.resposta_usuario, qr.data
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.acertou = 0
            ORDER BY qr.data DESC
        """).fetchall()
    return [dict(r) for r in rows]


# Estatísticas de questões (DEVE ficar antes de /api/questoes/{id})
@router.get("/api/questoes/stats/geral")
def questoes_stats():
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
        acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]
        por_materia = conn.execute("""
            SELECT q.materia,
                   COUNT(*) as total,
                   SUM(qr.acertou) as acertos
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            GROUP BY q.materia
            ORDER BY q.materia
        """).fetchall()
    return {
        "total_resolvidas": total,
        "total_acertos": acertos,
        "percentual": round((acertos / total * 100) if total > 0 else 0, 1),
        "por_materia": [dict(r) for r in por_materia]
    }


@router.get("/api/questoes/{id}")
def get_questao(id: int):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM questoes WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return dict(row)


@router.post("/api/questoes", summary="Criar questão", description="Adiciona uma nova questão ao banco de questões")
def create_questao(body: QuestaoCreate):
    with get_db() as conn:
        cur = conn.execute("""
            INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (body.materia, body.topico, body.enunciado, body.alternativa_a, body.alternativa_b,
              body.alternativa_c, body.alternativa_d, body.alternativa_e, body.resposta_correta,
              body.explicacao, body.dificuldade, today_str()))
        conn.commit()
        new_id = cur.lastrowid
    log.info(f"Questão created: id={new_id} materia={body.materia}")
    return {"id": new_id, "ok": True}


@router.post("/api/questoes/{id}/responder", summary="Responder questão", description="Registra a resposta do usuário e retorna se acertou ou errou")
def responder_questao(id: int, body: QuestaoResposta):
    with get_db() as conn:
        questao = conn.execute("SELECT resposta_correta FROM questoes WHERE id = ?", (id,)).fetchone()
        if not questao:
            raise HTTPException(404)
        acertou = 1 if body.resposta.upper() == questao[0].upper() else 0
        conn.execute("""
            INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data)
            VALUES (?, ?, ?, ?, ?)
        """, (id, body.resposta, acertou, body.tempo_segundos, today_str()))
        # Atualizar streak
        conn.execute("""
            INSERT INTO streaks (data, questoes_resolvidas) VALUES (?, 1)
            ON CONFLICT(data) DO UPDATE SET questoes_resolvidas = questoes_resolvidas + 1
        """, (today_str(),))
        conn.commit()
    return {"acertou": bool(acertou), "resposta_correta": questao[0]}


@router.delete("/api/questoes/{id}")
def delete_questao(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM questoes_respostas WHERE questao_id = ?", (id,))
        conn.execute("DELETE FROM questoes WHERE id = ?", (id,))
        conn.commit()
    log.info(f"Questão deleted: id={id}")
    return {"ok": True}


@router.get("/api/daily-challenge")
def daily_challenge():
    """Retorna a questão do dia (uma aleatória não respondida hoje)"""
    with get_db() as conn:
        # Buscar questões não respondidas hoje
        respondidas_hoje = conn.execute(
            "SELECT questao_id FROM questoes_respostas WHERE data = ?", (today_str(),)
        ).fetchall()
        ids_hoje = [r[0] for r in respondidas_hoje]

        if ids_hoje:
            placeholders = ','.join('?' * len(ids_hoje))
            rows = conn.execute(f"SELECT * FROM questoes WHERE id NOT IN ({placeholders})", ids_hoje).fetchall()
        else:
            rows = conn.execute("SELECT * FROM questoes").fetchall()

    if not rows:
        return {"message": "Parabéns! Você já respondeu todas as questões disponíveis hoje.", "questao": None}

    chosen = random.choice(rows)
    return {"questao": dict(chosen)}


@router.get("/api/active-recall/{materia}")
def active_recall_session(materia: str):
    """Gera uma sessão de active recall: questões aleatórias de uma matéria"""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM questoes WHERE materia = ?", (materia,)).fetchall()
    if not rows:
        return {"questoes": [], "message": "Nenhuma questão disponível para esta matéria."}
    sample = random.sample([dict(r) for r in rows], min(5, len(rows)))
    return {"questoes": sample, "materia": materia, "total": len(sample)}


@router.get("/api/intercalacao")
def intercalacao_forcada():
    """Sorteia tópicos de matérias DIFERENTES para estudo intercalado"""
    with get_db() as conn:
        materias = conn.execute("SELECT DISTINCT materia FROM edital WHERE status != 'Concluído'").fetchall()
        if len(materias) < 2:
            return {"topicos": [], "message": "Precisa de pelo menos 2 matérias não concluídas."}

        selected_mats = random.sample([r[0] for r in materias], min(3, len(materias)))
        topicos = []
        for mat in selected_mats:
            rows = conn.execute(
                "SELECT id, materia, topico FROM edital WHERE materia = ? AND status != 'Concluído' ORDER BY RANDOM() LIMIT 2",
                (mat,)
            ).fetchall()
            topicos.extend([dict(r) for r in rows])
    random.shuffle(topicos)
    return {"topicos": topicos, "materias": selected_mats}


@router.get("/api/questoes-vinculadas/{edital_id}")
def questoes_vinculadas(edital_id: int):
    """Busca questões que correspondem ao tópico de um item do edital"""
    with get_db() as conn:
        topico = conn.execute("SELECT materia, topico FROM edital WHERE id = ?", (edital_id,)).fetchone()
        if not topico:
            raise HTTPException(404)
        rows = conn.execute("SELECT id, enunciado, resposta_correta FROM questoes WHERE materia = ? LIMIT 10",
                            (topico[0],)).fetchall()
    return {"materia": topico[0], "topico": topico[1], "questoes": [dict(r) for r in rows]}


@router.get("/api/gerar-questao/{edital_id}")
def gerar_questao_template(edital_id: int):
    """Gera um template de questão baseado no tópico do edital"""
    with get_db() as conn:
        topico = conn.execute("SELECT materia, topico FROM edital WHERE id = ?", (edital_id,)).fetchone()
    if not topico:
        raise HTTPException(404)
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

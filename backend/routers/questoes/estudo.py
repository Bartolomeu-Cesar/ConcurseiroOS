"""Funcionalidades de estudo: daily challenge, active recall, intercalação, questões vinculadas, template."""
import random

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from utils import today_str

router = APIRouter()


@router.get("/api/daily-challenge")
def daily_challenge(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a questão do dia (uma aleatória não respondida hoje)"""
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

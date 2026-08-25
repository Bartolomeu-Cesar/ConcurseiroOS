"""Endpoints de discussão colaborativa: start, respond, comment, reveal, listar."""
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log

from .helpers import get_user_name
from .tables import ensure_discussion_tables

router = APIRouter(prefix="/api/studyroom", tags=["Study Room"])


# ============================================================
# COLLABORATIVE QUESTION DISCUSSION
# ============================================================


@router.post("/discussion/{codigo}/start")
def start_discussion(
    codigo: str,
    questao_id: int = Body(None, embed=True),
    enunciado: str = Body(None, embed=True),
    alternativas: list = Body(None, embed=True),
    resposta_correta: str = Body(None, embed=True),
    materia: str = Body("", embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Inicia uma discussão sobre uma questão. Pode buscar da base ou criar custom."""
    ensure_discussion_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    final_enunciado = enunciado
    final_alternativas = alternativas
    final_resposta = resposta_correta
    final_materia = materia
    final_questao_id = questao_id

    # Se questao_id fornecido, buscar da base
    if questao_id:
        questao = conn.execute("""
            SELECT id, enunciado, alternativas, resposta, materia
            FROM questoes WHERE id = ?
        """, (questao_id,)).fetchone()
        if not questao:
            raise HTTPException(status_code=404, detail="Questão não encontrada")

        final_enunciado = questao["enunciado"]
        alt = questao["alternativas"]
        if isinstance(alt, str):
            try:
                final_alternativas = json.loads(alt)
            except (json.JSONDecodeError, TypeError):
                final_alternativas = []
        else:
            final_alternativas = alt or []
        final_resposta = questao["resposta"]
        final_materia = questao["materia"] or ""
        final_questao_id = questao["id"]
    else:
        if not final_enunciado or not final_enunciado.strip():
            raise HTTPException(status_code=400, detail="Enunciado é obrigatório quando não há questao_id")

    alternativas_json = json.dumps(final_alternativas or [], ensure_ascii=False)
    now = datetime.now().isoformat()

    cursor = conn.execute("""
        INSERT INTO study_room_discussions
        (room_id, user_id, questao_id, enunciado, alternativas_json, resposta_correta, materia, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (room["id"], user_id, final_questao_id, final_enunciado.strip(), alternativas_json, final_resposta or "", final_materia, now))
    discussion_id = cursor.lastrowid
    conn.commit()

    log.info(f"Discussion started by user {user_id} in room {codigo}: discussion_id={discussion_id}")

    return {
        "ok": True,
        "discussion_id": discussion_id,
        "enunciado": final_enunciado.strip(),
        "alternativas": final_alternativas or [],
        "materia": final_materia,
    }


@router.post("/discussion/{codigo}/respond")
def respond_discussion(
    codigo: str,
    discussion_id: int = Body(..., embed=True),
    resposta: str = Body(..., embed=True),
    justificativa: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Submete resposta + justificativa para uma discussão."""
    ensure_discussion_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    discussion = conn.execute("""
        SELECT id, status FROM study_room_discussions
        WHERE id = ? AND room_id = ?
    """, (discussion_id, room["id"])).fetchone()

    if not discussion:
        raise HTTPException(status_code=404, detail="Discussão não encontrada")
    if discussion["status"] != "aberta":
        raise HTTPException(status_code=400, detail="Discussão já encerrada")

    if not resposta or not resposta.strip():
        raise HTTPException(status_code=400, detail="Resposta não pode ser vazia")
    if not justificativa or not justificativa.strip():
        raise HTTPException(status_code=400, detail="Justificativa não pode ser vazia")

    # Verificar se já respondeu
    existing = conn.execute("""
        SELECT id FROM study_room_discussion_responses
        WHERE discussion_id = ? AND user_id = ?
    """, (discussion_id, user_id)).fetchone()

    if existing:
        raise HTTPException(status_code=400, detail="Você já respondeu esta discussão")

    nome = get_user_name(conn, user_id)
    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_discussion_responses (discussion_id, user_id, nome, resposta, justificativa, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (discussion_id, user_id, nome, resposta.strip(), justificativa.strip(), now))
    conn.commit()

    log.info(f"Discussion response by user {user_id} for discussion {discussion_id}")
    return {"ok": True, "resposta": resposta.strip(), "justificativa": justificativa.strip()}


@router.post("/discussion/{codigo}/comment")
def comment_discussion(
    codigo: str,
    discussion_id: int = Body(..., embed=True),
    comentario: str = Body(..., embed=True),
    concordo: bool = Body(True, embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Comenta na discussão (concordar/discordar + argumentação)."""
    ensure_discussion_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    discussion = conn.execute("""
        SELECT id, status FROM study_room_discussions
        WHERE id = ? AND room_id = ?
    """, (discussion_id, room["id"])).fetchone()

    if not discussion:
        raise HTTPException(status_code=404, detail="Discussão não encontrada")

    if not comentario or not comentario.strip():
        raise HTTPException(status_code=400, detail="Comentário não pode ser vazio")

    # Buscar a última resposta da discussão para associar o comentário
    last_response = conn.execute("""
        SELECT id FROM study_room_discussion_responses
        WHERE discussion_id = ?
        ORDER BY created_at DESC LIMIT 1
    """, (discussion_id,)).fetchone()

    response_id = last_response["id"] if last_response else 0

    nome = get_user_name(conn, user_id)
    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_discussion_comments (discussion_id, response_id, user_id, nome, comentario, concordo, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (discussion_id, response_id, user_id, nome, comentario.strip(), int(concordo), now))
    conn.commit()

    log.info(f"Discussion comment by user {user_id} for discussion {discussion_id}")
    return {"ok": True, "comentario": comentario.strip(), "concordo": concordo}


@router.get("/discussion/{codigo}")
def listar_discussions(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna todas as discussões ativas da sala com respostas e comentários."""
    ensure_discussion_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    discussions = conn.execute("""
        SELECT id, user_id, questao_id, enunciado, alternativas_json, materia, status, created_at
        FROM study_room_discussions
        WHERE room_id = ?
        ORDER BY created_at DESC
    """, (room["id"],)).fetchall()

    result = []
    for d in discussions:
        # Buscar respostas
        responses = conn.execute("""
            SELECT id, user_id, nome, resposta, justificativa, created_at
            FROM study_room_discussion_responses
            WHERE discussion_id = ?
            ORDER BY created_at ASC
        """, (d["id"],)).fetchall()

        responses_list = []
        for r in responses:
            # Buscar comentários desta resposta
            comments = conn.execute("""
                SELECT id, user_id, nome, comentario, concordo, created_at
                FROM study_room_discussion_comments
                WHERE response_id = ?
                ORDER BY created_at ASC
            """, (r["id"],)).fetchall()

            responses_list.append({
                "id": r["id"],
                "user_id": r["user_id"],
                "nome": r["nome"],
                "resposta": r["resposta"],
                "justificativa": r["justificativa"],
                "created_at": r["created_at"],
                "comments": [
                    {
                        "id": c["id"],
                        "user_id": c["user_id"],
                        "nome": c["nome"],
                        "comentario": c["comentario"],
                        "concordo": bool(c["concordo"]),
                        "created_at": c["created_at"],
                    }
                    for c in comments
                ],
            })

        try:
            alternativas = json.loads(d["alternativas_json"]) if d["alternativas_json"] else []
        except (json.JSONDecodeError, TypeError):
            alternativas = []

        result.append({
            "id": d["id"],
            "user_id": d["user_id"],
            "questao_id": d["questao_id"],
            "enunciado": d["enunciado"],
            "alternativas": alternativas,
            "materia": d["materia"],
            "status": d["status"],
            "created_at": d["created_at"],
            "responses": responses_list,
        })

    return {"discussions": result}


@router.post("/discussion/{codigo}/reveal")
def reveal_discussion(
    codigo: str,
    discussion_id: int = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Revela a resposta correta da discussão (apenas criador da sala ou após todos responderem)."""
    ensure_discussion_tables(conn)

    room = conn.execute("SELECT id, criador_id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    discussion = conn.execute("""
        SELECT id, resposta_correta, status FROM study_room_discussions
        WHERE id = ? AND room_id = ?
    """, (discussion_id, room["id"])).fetchone()

    if not discussion:
        raise HTTPException(status_code=404, detail="Discussão não encontrada")

    if discussion["status"] == "revelada":
        return {"ok": True, "resposta_correta": discussion["resposta_correta"], "ja_revelada": True}

    # Verificar permissão: criador da sala OU todos participantes já responderam
    is_criador = user_id == room["criador_id"]

    if not is_criador:
        # Verificar se todos participantes responderam
        total_participants = conn.execute("""
            SELECT COUNT(*) as cnt FROM study_room_participants WHERE room_id = ?
        """, (room["id"],)).fetchone()["cnt"]

        total_responses = conn.execute("""
            SELECT COUNT(*) as cnt FROM study_room_discussion_responses WHERE discussion_id = ?
        """, (discussion_id,)).fetchone()["cnt"]

        if total_responses < total_participants:
            raise HTTPException(
                status_code=403,
                detail="Apenas o criador da sala pode revelar antes de todos responderem"
            )

    # Revelar
    conn.execute("""
        UPDATE study_room_discussions SET status = 'revelada' WHERE id = ?
    """, (discussion_id,))
    conn.commit()

    log.info(f"Discussion {discussion_id} revealed by user {user_id} in room {codigo}")
    return {"ok": True, "resposta_correta": discussion["resposta_correta"], "ja_revelada": False}

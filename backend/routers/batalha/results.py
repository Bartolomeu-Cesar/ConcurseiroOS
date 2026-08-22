"""Endpoints de resultados: ranking, review, revanche."""
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id

from .helpers import _ensure_battle_tables, _generate_code

router = APIRouter(prefix="/api/batalha", tags=["Batalha de Questões"])


@router.get("/ranking/{codigo}", summary="Ranking final da batalha",
            description="Retorna o ranking completo com posição, pontos, acertos e tempo de cada jogador.",
            responses={404: {"description": "Sala não encontrada"}})
def ranking_batalha(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna o ranking final estilo Duolingo (pódio + estatísticas)."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    players = conn.execute("""
        SELECT user_id, nome, avatar, pontos, acertos, erros, tempo_total_seg, posicao
        FROM battle_players WHERE battle_id = ?
        ORDER BY pontos DESC, tempo_total_seg ASC
    """, (battle["id"],)).fetchall()

    # Estatísticas por rodada
    rounds_detail = []
    for r_num in range(1, battle["total_rodadas"] + 1):
        round_q = conn.execute(
            "SELECT materia, enunciado FROM battle_rounds WHERE battle_id = ? AND rodada_num = ?",
            (battle["id"], r_num)
        ).fetchone()
        answers = conn.execute(
            "SELECT user_id, acertou, tempo_seg, pontos_ganhos FROM battle_answers WHERE battle_id = ? AND rodada_num = ?",
            (battle["id"], r_num)
        ).fetchall()
        rounds_detail.append({
            "rodada": r_num,
            "materia": round_q["materia"] if round_q else "",
            "respostas": [dict(a) for a in answers],
        })

    # Emojis de posição (estilo Duolingo)
    position_emojis = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}

    ranking = []
    for p in players:
        pos = p["posicao"] or (players.index(p) + 1)
        total_q = p["acertos"] + p["erros"]
        pct = round(p["acertos"] / total_q * 100, 1) if total_q > 0 else 0
        ranking.append({
            "posicao": pos,
            "emoji": position_emojis.get(pos, "🎯"),
            "user_id": p["user_id"],
            "nome": p["nome"],
            "avatar": p["avatar"],
            "pontos": p["pontos"],
            "acertos": p["acertos"],
            "erros": p["erros"],
            "pct_acerto": pct,
            "tempo_total_seg": p["tempo_total_seg"],
            "tempo_medio_seg": round(p["tempo_total_seg"] / total_q, 1) if total_q > 0 else 0,
        })

    vencedor = ranking[0] if ranking else None

    return {
        "titulo": battle["titulo"],
        "codigo": battle["codigo"],
        "status": battle["status"],
        "total_rodadas": battle["total_rodadas"],
        "materias": json.loads(battle["materias"]),
        "ranking": ranking,
        "vencedor": vencedor,
        "rounds": rounds_detail,
    }


@router.get("/review/{codigo}", summary="Revisão pós-batalha")
def review_batalha(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna todas as questões da batalha com explicações para estudo pós-batalha."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    rounds = conn.execute("""
        SELECT rodada_num, materia, topico, enunciado, alternativas, resposta_correta
        FROM battle_rounds WHERE battle_id = ? ORDER BY rodada_num
    """, (battle["id"],)).fetchall()

    # Respostas do usuário
    my_answers = conn.execute("""
        SELECT rodada_num, resposta, acertou, tempo_seg, pontos_ganhos
        FROM battle_answers WHERE battle_id = ? AND user_id = ?
    """, (battle["id"], user_id)).fetchall()
    my_map = {a["rodada_num"]: dict(a) for a in my_answers}

    # Buscar explicações das questões originais
    review = []
    for r in rounds:
        my_resp = my_map.get(r["rodada_num"], {})
        # Tentar buscar explicação do banco de questões
        explicacao = ""
        q_id_row = conn.execute(
            "SELECT questao_id FROM battle_rounds WHERE battle_id = ? AND rodada_num = ?",
            (battle["id"], r["rodada_num"])
        ).fetchone()
        if q_id_row and q_id_row["questao_id"]:
            q_orig = conn.execute("SELECT explicacao FROM questoes WHERE id = ?", (q_id_row["questao_id"],)).fetchone()
            if q_orig and q_orig["explicacao"]:
                explicacao = q_orig["explicacao"]

        review.append({
            "rodada": r["rodada_num"],
            "materia": r["materia"],
            "topico": r["topico"],
            "enunciado": r["enunciado"],
            "alternativas": json.loads(r["alternativas"]),
            "resposta_correta": r["resposta_correta"],
            "minha_resposta": my_resp.get("resposta", ""),
            "acertei": bool(my_resp.get("acertou", 0)),
            "tempo_seg": my_resp.get("tempo_seg", 0),
            "pontos": my_resp.get("pontos_ganhos", 0),
            "explicacao": explicacao,
        })

    acertos = sum(1 for r in review if r["acertei"])
    total = len(review)

    return {
        "titulo": battle["titulo"],
        "materias": json.loads(battle["materias"]),
        "questoes": review,
        "resumo": {
            "total": total,
            "acertos": acertos,
            "pct_acerto": round(acertos / total * 100, 1) if total > 0 else 0,
        },
    }


@router.post("/revanche/{codigo}", summary="Criar revanche")
def revanche(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Cria nova batalha com as mesmas configurações (revanche rápida)."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala original não encontrada.")

    # Criar nova sala com mesmas configs
    novo_codigo = _generate_code()
    while conn.execute("SELECT id FROM battles WHERE codigo = ?", (novo_codigo,)).fetchone():
        novo_codigo = _generate_code()

    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO battles (codigo, criador_id, titulo, materias, total_rodadas, tempo_por_questao, max_jogadores, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'aguardando', ?)
    """, (novo_codigo, user_id, f"Revanche: {battle['titulo']}", battle["materias"],
          battle["total_rodadas"], battle["tempo_por_questao"], battle["max_jogadores"], now))

    new_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Adicionar criador
    user = conn.execute("SELECT nome, avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    nome = user["nome"] if user else "Jogador"
    conn.execute(
        "INSERT INTO battle_players (battle_id, user_id, nome, avatar, joined_at) VALUES (?, ?, ?, ?, ?)",
        (new_id, user_id, nome, user["avatar"] if user else "", now)
    )
    conn.commit()

    return {"codigo": novo_codigo, "id": new_id, "message": "Revanche criada! Compartilhe o novo código."}

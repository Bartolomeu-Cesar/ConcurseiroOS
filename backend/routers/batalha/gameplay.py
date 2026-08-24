"""Endpoints de gameplay: iniciar, responder, avancar."""
import json
import random
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import IniciarBatalhaRequest, ResponderRodadaRequest
from utils import today_str

from .helpers import _calculate_points, _ensure_battle_tables, _is_battle_admin

router = APIRouter(prefix="/api/batalha", tags=["Batalha de Questões"])


@router.post("/iniciar/{codigo}", summary="Iniciar batalha",
             description="Inicia a batalha (apenas o criador pode). Gera as questões das rodadas baseado nas matérias selecionadas ou IDs específicos.",
             responses={403: {"description": "Apenas o criador pode iniciar"}, 404: {"description": "Sala não encontrada"}})
def iniciar_batalha(
    codigo: str,
    body: IniciarBatalhaRequest = None,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Inicia a batalha (apenas o criador pode). Gera as questões para todas as rodadas."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    if not _is_battle_admin(battle, user_id):
        raise HTTPException(status_code=403, detail="Apenas o criador ou coautor pode iniciar a batalha.")

    if battle["status"] != "aguardando":
        raise HTTPException(status_code=400, detail="Batalha já foi iniciada.")

    player_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM battle_players WHERE battle_id = ?", (battle["id"],)
    ).fetchone()["cnt"]
    if player_count < 2:
        raise HTTPException(status_code=400, detail="Mínimo 2 jogadores para iniciar.")

    # Gerar questões para todas as rodadas — DIFICULDADE PROGRESSIVA
    materias = json.loads(battle["materias"])
    total = battle["total_rodadas"]

    # Se o criador enviou IDs específicos, usar essas questões
    questao_ids = (body.questao_ids if body else []) or []

    if questao_ids:
        # Pool manual selecionado pelo criador
        placeholders = ",".join("?" * len(questao_ids))
        questoes_raw = conn.execute(f"""
            SELECT id, materia, topico, enunciado, alternativa_a, alternativa_b,
                   alternativa_c, alternativa_d, alternativa_e, resposta_correta, dificuldade
            FROM questoes WHERE id IN ({placeholders}) AND user_id = ?
            AND resposta_correta != '' AND resposta_correta IS NOT NULL
        """, (*questao_ids, user_id)).fetchall()
        # Embaralhar aleatoriamente
        questoes_raw = list(questoes_raw)
        random.shuffle(questoes_raw)
        # Pegar a quantidade de rodadas
        todas = questoes_raw
        questoes = todas[:total]
        # Se precisar mais, repetir
        while len(questoes) < total and questoes:
            questoes.extend(questoes[:total - len(questoes)])
        questoes = questoes[:total]
    else:
        # Buscar questões disponíveis, organizadas por dificuldade
        # Dificuldade: Fácil → Médio → Difícil (progressivo ao longo das rodadas)
        difficulty_order = "CASE dificuldade WHEN 'Fácil' THEN 1 WHEN 'Médio' THEN 2 WHEN 'Difícil' THEN 3 ELSE 2 END"

        if materias:
            placeholders = ",".join("?" * len(materias))
            questoes_raw = conn.execute(f"""
                SELECT id, materia, topico, enunciado, alternativa_a, alternativa_b,
                       alternativa_c, alternativa_d, alternativa_e, resposta_correta, dificuldade
                FROM questoes WHERE materia IN ({placeholders}) AND user_id = ?
                AND resposta_correta != '' AND resposta_correta IS NOT NULL
                ORDER BY {difficulty_order}, RANDOM()
            """, (*materias, user_id)).fetchall()
        else:
            questoes_raw = conn.execute(f"""
                SELECT id, materia, topico, enunciado, alternativa_a, alternativa_b,
                       alternativa_c, alternativa_d, alternativa_e, resposta_correta, dificuldade
                FROM questoes WHERE user_id = ?
                AND resposta_correta != '' AND resposta_correta IS NOT NULL
                ORDER BY {difficulty_order}, RANDOM()
            """, (user_id,)).fetchall()

        # Distribuir progressivamente: 1/3 fácil, 1/3 médio, 1/3 difícil
        faceis = [q for q in questoes_raw if (q["dificuldade"] or "Médio") == "Fácil"]
        medias = [q for q in questoes_raw if (q["dificuldade"] or "Médio") == "Médio"]
        dificeis = [q for q in questoes_raw if (q["dificuldade"] or "Médio") == "Difícil"]

        # Embaralhar dentro de cada grupo
        random.shuffle(faceis)
        random.shuffle(medias)
        random.shuffle(dificeis)

        # Distribuir: primeiras rodadas fáceis, meio médias, finais difíceis
        terco = max(1, total // 3)
        questoes = []
        questoes.extend(faceis[:terco])
        questoes.extend(medias[:terco])
        questoes.extend(dificeis[:total - 2 * terco])

        # Se não tem questões suficientes de algum nível, completar com as disponíveis
        todas = faceis + medias + dificeis
        random.shuffle(todas)
        while len(questoes) < total and todas:
            q = todas.pop(0)
            if q not in questoes:
                questoes.append(q)

        if len(questoes) < total:
            # Preencher com repetições se necessário
            while len(questoes) < total and questoes:
                questoes.extend(questoes[:total - len(questoes)])
            questoes = questoes[:total]

    if not questoes:
        raise HTTPException(status_code=400, detail="Sem questões disponíveis para as matérias selecionadas.")

    now = datetime.now().isoformat()
    for i, q in enumerate(questoes, 1):
        alts = json.dumps({
            "a": q["alternativa_a"],
            "b": q["alternativa_b"],
            "c": q["alternativa_c"],
            "d": q["alternativa_d"],
            "e": q["alternativa_e"] or "",
        })
        conn.execute("""
            INSERT INTO battle_rounds (battle_id, rodada_num, questao_id, materia, topico, enunciado, alternativas, resposta_correta, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (battle["id"], i, q["id"], q["materia"], q["topico"] or "", q["enunciado"], alts, q["resposta_correta"], now))

    # Iniciar: rodada 1
    conn.execute("UPDATE battles SET status = 'em_andamento', rodada_atual = 1 WHERE id = ?", (battle["id"],))
    conn.commit()

    log.info(f"[batalha] Sala {codigo} iniciada! {total} rodadas, {player_count} jogadores")
    return {"message": "Batalha iniciada!", "total_rodadas": total, "jogadores": player_count}


@router.post("/responder/{codigo}", summary="Responder questão da rodada",
             description="Registra a resposta do jogador para a rodada atual. Pontos calculados por: acerto + velocidade + streak. Avança automaticamente quando todos respondem.",
             responses={400: {"description": "Já respondeu esta rodada"}, 404: {"description": "Sala não encontrada"}})
def responder_rodada(
    codigo: str,
    body: ResponderRodadaRequest,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Jogador responde a questão da rodada atual. Resposta é a letra VISUAL (já mapeada no frontend)."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    if battle["status"] != "em_andamento":
        raise HTTPException(status_code=400, detail="Batalha não está em andamento.")

    # Verificar se é jogador
    player = conn.execute(
        "SELECT id FROM battle_players WHERE battle_id = ? AND user_id = ?", (battle["id"], user_id)
    ).fetchone()
    if not player:
        raise HTTPException(status_code=403, detail="Você não está nesta batalha.")

    rodada_num = battle["rodada_atual"]
    resposta_visual = body.resposta.strip().lower()
    tempo_seg = max(0, min(battle["tempo_por_questao"] * 2, body.tempo_seg))

    # Verificar se já respondeu esta rodada
    existing = conn.execute(
        "SELECT id FROM battle_answers WHERE battle_id = ? AND rodada_num = ? AND user_id = ?",
        (battle["id"], rodada_num, user_id)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Você já respondeu esta rodada.")

    # Buscar dados da rodada
    round_data = conn.execute(
        "SELECT resposta_correta, alternativas FROM battle_rounds WHERE battle_id = ? AND rodada_num = ?",
        (battle["id"], rodada_num)
    ).fetchone()
    if not round_data:
        raise HTTPException(status_code=400, detail="Rodada não encontrada.")

    # Desfazer o shuffle: converter letra visual → letra real
    # Rebuild mapping para este user (mesma seed que no status_sala)
    alts_original = json.loads(round_data["alternativas"])
    alt_items = [(k, v) for k, v in alts_original.items() if v]
    rng = random.Random(user_id * 1000 + rodada_num)
    rng.shuffle(alt_items)
    visual_letters = ['a', 'b', 'c', 'd', 'e'][:len(alt_items)]
    mapping = {}  # visual → real
    for i, (real_letter, _text) in enumerate(alt_items):
        mapping[visual_letters[i]] = real_letter

    # Traduzir resposta visual → real
    resposta_real = mapping.get(resposta_visual, resposta_visual)

    resposta_correta = round_data["resposta_correta"].strip().lower()
    acertou = resposta_real == resposta_correta

    # Calcular streak (acertos consecutivos nesta batalha)
    prev_answers = conn.execute("""
        SELECT acertou FROM battle_answers
        WHERE battle_id = ? AND user_id = ?
        ORDER BY rodada_num DESC
    """, (battle["id"], user_id)).fetchall()
    streak = 0
    for pa in prev_answers:
        if pa["acertou"]:
            streak += 1
        else:
            break
    if acertou:
        streak += 1  # Inclui a resposta atual

    pontos = _calculate_points(acertou, tempo_seg, battle["tempo_por_questao"], streak if acertou else 0)

    # Determinar a letra visual da resposta correta (para feedback ao jogador)
    resposta_correta_visual = resposta_visual  # fallback
    for vl, rl in mapping.items():
        if rl == resposta_correta:
            resposta_correta_visual = vl
            break

    conn.execute("""
        INSERT INTO battle_answers (battle_id, rodada_num, user_id, resposta, acertou, tempo_seg, pontos_ganhos, answered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (battle["id"], rodada_num, user_id, resposta_real, int(acertou), tempo_seg, pontos, datetime.now().isoformat()))

    # Atualizar pontos do jogador
    conn.execute("""
        UPDATE battle_players
        SET pontos = pontos + ?, acertos = acertos + ?, erros = erros + ?, tempo_total_seg = tempo_total_seg + ?
        WHERE battle_id = ? AND user_id = ?
    """, (pontos, int(acertou), int(not acertou), tempo_seg, battle["id"], user_id))
    conn.commit()

    # Verificar se todos responderam → avançar rodada
    total_players = conn.execute(
        "SELECT COUNT(*) as cnt FROM battle_players WHERE battle_id = ?", (battle["id"],)
    ).fetchone()["cnt"]
    total_answers = conn.execute(
        "SELECT COUNT(*) as cnt FROM battle_answers WHERE battle_id = ? AND rodada_num = ?",
        (battle["id"], rodada_num)
    ).fetchone()["cnt"]

    rodada_completa = total_answers >= total_players
    batalha_finalizada = False

    if rodada_completa:
        if rodada_num >= battle["total_rodadas"]:
            # Finalizar batalha
            conn.execute("UPDATE battles SET status = 'finalizada', rodada_atual = ? WHERE id = ?", (rodada_num, battle["id"]))
            # Calcular posições
            players = conn.execute(
                "SELECT user_id, pontos, tempo_total_seg FROM battle_players WHERE battle_id = ? ORDER BY pontos DESC, tempo_total_seg ASC",
                (battle["id"],)
            ).fetchall()
            for i, p in enumerate(players, 1):
                conn.execute("UPDATE battle_players SET posicao = ? WHERE battle_id = ? AND user_id = ?",
                             (i, battle["id"], p["user_id"]))

            # Registrar tempo de batalha como tempo de estudo para cada jogador
            materias_batalha = json.loads(battle["materias"]) or []
            materia_registro = materias_batalha[0] if materias_batalha else "Batalha de Questões"
            data_hoje = today_str()
            for p in players:
                horas = round(p["tempo_total_seg"] / 3600, 4)
                if horas > 0:
                    conn.execute(
                        "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'batalha', ?)",
                        (materia_registro, horas, data_hoje, p["user_id"])
                    )

            batalha_finalizada = True
        else:
            # Avançar para próxima rodada
            conn.execute("UPDATE battles SET rodada_atual = ? WHERE id = ?", (rodada_num + 1, battle["id"]))
        conn.commit()

    return {
        "acertou": acertou,
        "pontos_ganhos": pontos,
        "resposta_correta": resposta_correta_visual.upper(),  # Letra VISUAL para o frontend
        "streak": streak if acertou else 0,
        "streak_bonus": "🔥 2x!" if streak >= 5 else "⚡ 1.5x!" if streak >= 3 else None,
        "rodada_completa": rodada_completa,
        "batalha_finalizada": batalha_finalizada,
        "proxima_rodada": rodada_num + 1 if rodada_completa and not batalha_finalizada else rodada_num,
    }


@router.post("/avancar/{codigo}", summary="Forçar avanço de rodada (moderador)")
def avancar_rodada(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Moderador pode forçar avanço de rodada (timeout de jogadores lentos)."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    if not _is_battle_admin(battle, user_id):
            raise HTTPException(status_code=403, detail="Apenas o criador ou coautor pode avançar.")

    if battle["status"] != "em_andamento":
        raise HTTPException(status_code=400, detail="Batalha não está em andamento.")

    rodada_num = battle["rodada_atual"]

    # Jogadores que não responderam recebem 0 pontos
    players = conn.execute("SELECT user_id FROM battle_players WHERE battle_id = ?", (battle["id"],)).fetchall()
    for p in players:
        existing = conn.execute(
            "SELECT id FROM battle_answers WHERE battle_id = ? AND rodada_num = ? AND user_id = ?",
            (battle["id"], rodada_num, p["user_id"])
        ).fetchone()
        if not existing:
            conn.execute("""
                INSERT INTO battle_answers (battle_id, rodada_num, user_id, resposta, acertou, tempo_seg, pontos_ganhos, answered_at)
                VALUES (?, ?, ?, '', 0, ?, 0, ?)
            """, (battle["id"], rodada_num, p["user_id"], battle["tempo_por_questao"], datetime.now().isoformat()))
            conn.execute("""
                UPDATE battle_players SET erros = erros + 1, tempo_total_seg = tempo_total_seg + ?
                WHERE battle_id = ? AND user_id = ?
            """, (battle["tempo_por_questao"], battle["id"], p["user_id"]))

    # Avançar ou finalizar
    if rodada_num >= battle["total_rodadas"]:
        conn.execute("UPDATE battles SET status = 'finalizada' WHERE id = ?", (battle["id"],))
        # Posições
        ranked = conn.execute(
            "SELECT user_id FROM battle_players WHERE battle_id = ? ORDER BY pontos DESC, tempo_total_seg ASC",
            (battle["id"],)
        ).fetchall()
        for i, r in enumerate(ranked, 1):
            conn.execute("UPDATE battle_players SET posicao = ? WHERE battle_id = ? AND user_id = ?",
                         (i, battle["id"], r["user_id"]))
        conn.commit()
        return {"message": "Batalha finalizada!", "finalizada": True}
    else:
        conn.execute("UPDATE battles SET rodada_atual = ? WHERE id = ?", (rodada_num + 1, battle["id"]))
        conn.commit()
        return {"message": f"Rodada {rodada_num + 1} iniciada!", "finalizada": False, "rodada": rodada_num + 1}

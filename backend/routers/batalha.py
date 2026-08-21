"""
Router de Batalha de Questões (Multiplayer) — estilo Duolingo.
Até 5 jogadores, rodadas configuráveis, matérias selecionáveis.
"""
import json
import random
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from utils import today_str

router = APIRouter(prefix="/api/batalha", tags=["Batalha de Questões"])


# ============================================================
# TABELAS (criadas via migration no init_db)
# ============================================================
# battles: id, codigo, criador_id, titulo, materias (JSON), total_rodadas,
#           rodada_atual, status (aguardando|em_andamento|finalizada),
#           tempo_por_questao, created_at
#
# battle_players: id, battle_id, user_id, nome, avatar, pontos, acertos,
#                 erros, tempo_total_seg, posicao, joined_at
#
# battle_rounds: id, battle_id, rodada_num, questao_id, materia, topico,
#                enunciado, alternativas (JSON), resposta_correta, created_at
#
# battle_answers: id, battle_id, rodada_num, user_id, resposta,
#                 acertou, tempo_seg, pontos_ganhos, answered_at


def _ensure_battle_tables(conn):
    """Cria tabelas de batalha se não existirem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            criador_id INTEGER NOT NULL,
            titulo TEXT DEFAULT 'Batalha de Questões',
            materias TEXT DEFAULT '[]',
            total_rodadas INTEGER DEFAULT 5,
            rodada_atual INTEGER DEFAULT 0,
            status TEXT DEFAULT 'aguardando',
            tempo_por_questao INTEGER DEFAULT 30,
            max_jogadores INTEGER DEFAULT 5,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battle_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT 'Jogador',
            avatar TEXT DEFAULT '',
            pontos INTEGER DEFAULT 0,
            acertos INTEGER DEFAULT 0,
            erros INTEGER DEFAULT 0,
            tempo_total_seg INTEGER DEFAULT 0,
            posicao INTEGER DEFAULT 0,
            joined_at TEXT NOT NULL,
            FOREIGN KEY (battle_id) REFERENCES battles(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battle_rounds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            rodada_num INTEGER NOT NULL,
            questao_id INTEGER,
            materia TEXT DEFAULT '',
            topico TEXT DEFAULT '',
            enunciado TEXT NOT NULL,
            alternativas TEXT NOT NULL,
            resposta_correta TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (battle_id) REFERENCES battles(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS battle_answers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            battle_id INTEGER NOT NULL,
            rodada_num INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            resposta TEXT DEFAULT '',
            acertou INTEGER DEFAULT 0,
            tempo_seg INTEGER DEFAULT 0,
            pontos_ganhos INTEGER DEFAULT 0,
            answered_at TEXT NOT NULL,
            FOREIGN KEY (battle_id) REFERENCES battles(id)
        )
    """)
    conn.commit()


def _generate_code():
    """Gera código de sala de 6 caracteres."""
    chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(random.choices(chars, k=6))


def _calculate_points(acertou: bool, tempo_seg: int, tempo_max: int) -> int:
    """Calcula pontos estilo Duolingo: acerto + bonus por velocidade."""
    if not acertou:
        return 0
    # Base: 100 pontos por acerto
    base = 100
    # Bonus por velocidade: até 50 pontos extras (quanto mais rápido, mais pontos)
    if tempo_max > 0 and tempo_seg < tempo_max:
        speed_bonus = int(50 * (1 - tempo_seg / tempo_max))
    else:
        speed_bonus = 0
    return base + speed_bonus


# ============================================================
# ENDPOINTS
# ============================================================

@router.post("/criar", summary="Criar sala de batalha")
def criar_batalha(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """
    Cria uma nova sala de batalha.
    Body: {titulo, materias: ["Dir. Penal", "Dir. Const."], total_rodadas: 5-20, tempo_por_questao: 15-60, max_jogadores: 2-5}
    """
    _ensure_battle_tables(conn)

    titulo = body.get("titulo", "Batalha de Questões")
    materias = body.get("materias", [])
    total_rodadas = max(3, min(20, int(body.get("total_rodadas", 5))))
    tempo_por_questao = max(10, min(120, int(body.get("tempo_por_questao", 30))))
    max_jogadores = max(2, min(5, int(body.get("max_jogadores", 5))))

    codigo = _generate_code()
    # Garantir unicidade
    while conn.execute("SELECT id FROM battles WHERE codigo = ?", (codigo,)).fetchone():
        codigo = _generate_code()

    now = datetime.now().isoformat()
    conn.execute("""
        INSERT INTO battles (codigo, criador_id, titulo, materias, total_rodadas, tempo_por_questao, max_jogadores, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'aguardando', ?)
    """, (codigo, user_id, titulo, json.dumps(materias), total_rodadas, tempo_por_questao, max_jogadores, now))

    battle_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Criador entra automaticamente
    user = conn.execute("SELECT nome, avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    nome = user["nome"] if user else "Jogador 1"
    avatar = user["avatar"] if user else ""
    conn.execute(
        "INSERT INTO battle_players (battle_id, user_id, nome, avatar, joined_at) VALUES (?, ?, ?, ?, ?)",
        (battle_id, user_id, nome, avatar, now)
    )
    conn.commit()

    log.info(f"[batalha] Sala criada: {codigo} por user={user_id} ({total_rodadas} rodadas, materias={materias})")
    return {
        "id": battle_id,
        "codigo": codigo,
        "titulo": titulo,
        "materias": materias,
        "total_rodadas": total_rodadas,
        "tempo_por_questao": tempo_por_questao,
        "max_jogadores": max_jogadores,
        "status": "aguardando",
    }


@router.post("/entrar", summary="Entrar em sala de batalha")
def entrar_batalha(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Entra em uma sala pelo código."""
    _ensure_battle_tables(conn)
    codigo = body.get("codigo", "").strip().upper()
    if not codigo:
        raise HTTPException(status_code=400, detail="Código da sala é obrigatório.")

    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo,)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada. Verifique o código.")

    if battle["status"] != "aguardando":
        raise HTTPException(status_code=400, detail="Esta batalha já começou ou foi finalizada.")

    # Check if already in
    existing = conn.execute(
        "SELECT id FROM battle_players WHERE battle_id = ? AND user_id = ?", (battle["id"], user_id)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Você já está nesta sala.")

    # Check max players
    count = conn.execute(
        "SELECT COUNT(*) as cnt FROM battle_players WHERE battle_id = ?", (battle["id"],)
    ).fetchone()["cnt"]
    if count >= battle["max_jogadores"]:
        raise HTTPException(status_code=400, detail=f"Sala cheia ({count}/{battle['max_jogadores']}).")

    user = conn.execute("SELECT nome, avatar FROM users WHERE id = ?", (user_id,)).fetchone()
    nome = body.get("nome") or (user["nome"] if user else f"Jogador {count + 1}")
    avatar = user["avatar"] if user else ""

    conn.execute(
        "INSERT INTO battle_players (battle_id, user_id, nome, avatar, joined_at) VALUES (?, ?, ?, ?, ?)",
        (battle["id"], user_id, nome, avatar, datetime.now().isoformat())
    )
    conn.commit()

    log.info(f"[batalha] {nome} entrou na sala {codigo}")
    return {"message": f"Bem-vindo à batalha!", "battle_id": battle["id"], "codigo": codigo}


@router.get("/sala/{codigo}", summary="Status da sala")
def status_sala(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna status completo da sala (jogadores, rodada atual, etc.)."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    players = conn.execute(
        "SELECT user_id, nome, avatar, pontos, acertos, erros, tempo_total_seg, posicao FROM battle_players WHERE battle_id = ? ORDER BY pontos DESC",
        (battle["id"],)
    ).fetchall()

    # Rodada atual
    current_round = None
    if battle["status"] == "em_andamento" and battle["rodada_atual"] > 0:
        round_data = conn.execute(
            "SELECT * FROM battle_rounds WHERE battle_id = ? AND rodada_num = ?",
            (battle["id"], battle["rodada_atual"])
        ).fetchone()
        if round_data:
            # Quem já respondeu nesta rodada
            answers = conn.execute(
                "SELECT user_id, acertou, tempo_seg, pontos_ganhos FROM battle_answers WHERE battle_id = ? AND rodada_num = ?",
                (battle["id"], battle["rodada_atual"])
            ).fetchall()
            current_round = {
                "rodada_num": round_data["rodada_num"],
                "materia": round_data["materia"],
                "topico": round_data["topico"],
                "enunciado": round_data["enunciado"],
                "alternativas": json.loads(round_data["alternativas"]),
                "responderam": [{"user_id": a["user_id"], "acertou": bool(a["acertou"]), "tempo_seg": a["tempo_seg"], "pontos": a["pontos_ganhos"]} for a in answers],
                "total_responderam": len(answers),
            }

    return {
        "id": battle["id"],
        "codigo": battle["codigo"],
        "titulo": battle["titulo"],
        "materias": json.loads(battle["materias"]),
        "total_rodadas": battle["total_rodadas"],
        "rodada_atual": battle["rodada_atual"],
        "status": battle["status"],
        "tempo_por_questao": battle["tempo_por_questao"],
        "max_jogadores": battle["max_jogadores"],
        "criador_id": battle["criador_id"],
        "jogadores": [dict(p) for p in players],
        "rodada": current_round,
    }


@router.post("/iniciar/{codigo}", summary="Iniciar batalha")
def iniciar_batalha(
    codigo: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Inicia a batalha (apenas o criador pode). Gera as questões para todas as rodadas."""
    _ensure_battle_tables(conn)
    battle = conn.execute("SELECT * FROM battles WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not battle:
        raise HTTPException(status_code=404, detail="Sala não encontrada.")

    if battle["criador_id"] != user_id:
        raise HTTPException(status_code=403, detail="Apenas o criador pode iniciar a batalha.")

    if battle["status"] != "aguardando":
        raise HTTPException(status_code=400, detail="Batalha já foi iniciada.")

    player_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM battle_players WHERE battle_id = ?", (battle["id"],)
    ).fetchone()["cnt"]
    if player_count < 2:
        raise HTTPException(status_code=400, detail="Mínimo 2 jogadores para iniciar.")

    # Gerar questões para todas as rodadas
    materias = json.loads(battle["materias"])
    total = battle["total_rodadas"]

    # Buscar questões disponíveis
    if materias:
        placeholders = ",".join("?" * len(materias))
        questoes = conn.execute(f"""
            SELECT id, materia, topico, enunciado, alternativa_a, alternativa_b,
                   alternativa_c, alternativa_d, alternativa_e, resposta_correta
            FROM questoes WHERE materia IN ({placeholders}) AND user_id = ?
            ORDER BY RANDOM() LIMIT ?
        """, (*materias, user_id, total)).fetchall()
    else:
        questoes = conn.execute("""
            SELECT id, materia, topico, enunciado, alternativa_a, alternativa_b,
                   alternativa_c, alternativa_d, alternativa_e, resposta_correta
            FROM questoes WHERE user_id = ? ORDER BY RANDOM() LIMIT ?
        """, (user_id, total)).fetchall()

    if len(questoes) < total:
        # Preencher com repetições se necessário
        while len(questoes) < total:
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


@router.post("/responder/{codigo}", summary="Responder questão da rodada")
def responder_rodada(
    codigo: str,
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Jogador responde a questão da rodada atual."""
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
    resposta = body.get("resposta", "").strip().lower()
    tempo_seg = max(0, min(battle["tempo_por_questao"] * 2, int(body.get("tempo_seg", 0))))

    # Verificar se já respondeu esta rodada
    existing = conn.execute(
        "SELECT id FROM battle_answers WHERE battle_id = ? AND rodada_num = ? AND user_id = ?",
        (battle["id"], rodada_num, user_id)
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Você já respondeu esta rodada.")

    # Buscar resposta correta
    round_data = conn.execute(
        "SELECT resposta_correta FROM battle_rounds WHERE battle_id = ? AND rodada_num = ?",
        (battle["id"], rodada_num)
    ).fetchone()
    if not round_data:
        raise HTTPException(status_code=400, detail="Rodada não encontrada.")

    acertou = resposta == round_data["resposta_correta"].strip().lower()
    pontos = _calculate_points(acertou, tempo_seg, battle["tempo_por_questao"])

    conn.execute("""
        INSERT INTO battle_answers (battle_id, rodada_num, user_id, resposta, acertou, tempo_seg, pontos_ganhos, answered_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (battle["id"], rodada_num, user_id, resposta, int(acertou), tempo_seg, pontos, datetime.now().isoformat()))

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
                "SELECT user_id, pontos FROM battle_players WHERE battle_id = ? ORDER BY pontos DESC, tempo_total_seg ASC",
                (battle["id"],)
            ).fetchall()
            for i, p in enumerate(players, 1):
                conn.execute("UPDATE battle_players SET posicao = ? WHERE battle_id = ? AND user_id = ?",
                             (i, battle["id"], p["user_id"]))
            batalha_finalizada = True
        else:
            # Avançar para próxima rodada
            conn.execute("UPDATE battles SET rodada_atual = ? WHERE id = ?", (rodada_num + 1, battle["id"]))
        conn.commit()

    return {
        "acertou": acertou,
        "pontos_ganhos": pontos,
        "resposta_correta": round_data["resposta_correta"],
        "rodada_completa": rodada_completa,
        "batalha_finalizada": batalha_finalizada,
        "proxima_rodada": rodada_num + 1 if rodada_completa and not batalha_finalizada else rodada_num,
    }


@router.get("/ranking/{codigo}", summary="Ranking final da batalha")
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


@router.get("/minhas", summary="Minhas batalhas")
def minhas_batalhas(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Lista batalhas que o usuário participou."""
    _ensure_battle_tables(conn)
    rows = conn.execute("""
        SELECT b.id, b.codigo, b.titulo, b.status, b.total_rodadas, b.created_at,
               bp.pontos, bp.posicao, bp.acertos, bp.erros
        FROM battles b
        JOIN battle_players bp ON bp.battle_id = b.id AND bp.user_id = ?
        ORDER BY b.created_at DESC
        LIMIT 20
    """, (user_id,)).fetchall()

    return [dict(r) for r in rows]


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

    if battle["criador_id"] != user_id:
        raise HTTPException(status_code=403, detail="Apenas o moderador pode avançar.")

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

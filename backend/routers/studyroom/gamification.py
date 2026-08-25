"""Endpoints de gamificação: commitment contract, challenge/boss fight, streak, nudge."""
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log

from .helpers import get_user_name
from .tables import ensure_challenge_tables, ensure_commitment_tables, ensure_studyroom_tables, run_studyroom_migrations

router = APIRouter(prefix="/api/studyroom", tags=["Study Room"])


# ============================================================
# 1. COMMITMENT CONTRACT
# ============================================================


@router.post("/commitment/{codigo}")
def criar_commitment(
    codigo: str,
    commitment: str = Body(..., embed=True),
    xp_stake: int = Body(50, embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Cria um commitment público para a sala."""
    ensure_commitment_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    if not commitment or not commitment.strip():
        raise HTTPException(status_code=400, detail="Commitment não pode ser vazio")

    if xp_stake < 0 or xp_stake > 500:
        raise HTTPException(status_code=400, detail="XP stake deve ser entre 0 e 500")

    nome = get_user_name(conn, user_id)
    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_commitments (room_id, user_id, nome, commitment, xp_stake, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (room["id"], user_id, nome, commitment.strip(), xp_stake, now))
    conn.commit()

    log.info(f"Commitment created by user {user_id} in room {codigo}: {commitment.strip()}")
    return {"ok": True, "commitment": commitment.strip(), "xp_stake": xp_stake}


@router.get("/commitment/{codigo}")
def listar_commitments(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna todos os commitments da sala."""
    ensure_commitment_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    rows = conn.execute("""
        SELECT id, user_id, nome, commitment, xp_stake, cumprida, created_at
        FROM study_room_commitments
        WHERE room_id = ?
        ORDER BY created_at DESC
    """, (room["id"],)).fetchall()

    return {
        "commitments": [
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "nome": r["nome"],
                "commitment": r["commitment"],
                "xp_stake": r["xp_stake"],
                "cumprida": r["cumprida"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.post("/commitment/{codigo}/resolve")
def resolver_commitment(
    codigo: str,
    cumprida: bool = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Resolve um commitment — se cumprido, ganha XP bônus; se não, perde XP."""
    ensure_commitment_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Buscar o commitment pendente mais recente do usuário nesta sala
    commitment = conn.execute("""
        SELECT id, xp_stake FROM study_room_commitments
        WHERE room_id = ? AND user_id = ? AND cumprida IS NULL
        ORDER BY created_at DESC LIMIT 1
    """, (room["id"], user_id)).fetchone()

    if not commitment:
        raise HTTPException(status_code=404, detail="Nenhum commitment pendente encontrado")

    xp_stake = commitment["xp_stake"]

    if cumprida:
        # Bonus XP (stake * 1.5)
        xp_ganho = int(xp_stake * 1.5)
        conn.execute(
            "UPDATE study_room_commitments SET cumprida = 1 WHERE id = ?",
            (commitment["id"],)
        )
    else:
        # Deduct XP
        xp_ganho = -xp_stake
        conn.execute(
            "UPDATE study_room_commitments SET cumprida = 0 WHERE id = ?",
            (commitment["id"],)
        )

    conn.commit()
    log.info(f"Commitment resolved by user {user_id}: cumprida={cumprida}, xp_change={xp_ganho}")

    return {
        "ok": True,
        "cumprida": cumprida,
        "xp_change": xp_ganho,
        "mensagem": "Parabéns! Commitment cumprido! 🎉" if cumprida else "Commitment não cumprido. XP deduzido. Tente novamente! 💪",
    }


# ============================================================
# 2. CHALLENGE MODE (BOSS FIGHT)
# ============================================================


@router.post("/challenge/{codigo}/start")
def start_challenge(
    codigo: str,
    materia: str = Body(..., embed=True),
    quantidade: int = Body(10, embed=True),
    tempo_limite_min: int = Body(15, embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Inicia um desafio Boss Fight — busca questões e cria o desafio."""
    ensure_challenge_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    if quantidade < 1 or quantidade > 50:
        raise HTTPException(status_code=400, detail="Quantidade deve ser entre 1 e 50")
    if tempo_limite_min < 1 or tempo_limite_min > 120:
        raise HTTPException(status_code=400, detail="Tempo limite deve ser entre 1 e 120 minutos")

    # Buscar questões da tabela questoes
    try:
        questoes = conn.execute("""
            SELECT id, enunciado, alternativas, resposta, materia
            FROM questoes
            WHERE materia LIKE ? AND user_id = ?
            ORDER BY RANDOM()
            LIMIT ?
        """, (f"%{materia}%", user_id, quantidade)).fetchall()
    except Exception:
        questoes = []

    if not questoes:
        raise HTTPException(status_code=404, detail=f"Nenhuma questão encontrada para a matéria '{materia}'")

    questoes_list = []
    for q in questoes:
        alternativas = q["alternativas"]
        if isinstance(alternativas, str):
            try:
                alternativas = json.loads(alternativas)
            except (json.JSONDecodeError, TypeError):
                alternativas = []
        questoes_list.append({
            "id": q["id"],
            "enunciado": q["enunciado"],
            "alternativas": alternativas,
            "materia": q["materia"],
        })

    now = datetime.now().isoformat()
    questoes_json = json.dumps(questoes_list, ensure_ascii=False)

    cursor = conn.execute("""
        INSERT INTO study_room_challenges (room_id, user_id, materia, quantidade, tempo_limite_min, boss_hp_atual, questoes_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (room["id"], user_id, materia, len(questoes_list), tempo_limite_min, len(questoes_list), questoes_json, now))
    challenge_id = cursor.lastrowid
    conn.commit()

    log.info(f"Challenge started by user {user_id} in room {codigo}: {materia}, {len(questoes_list)} questões")

    return {
        "challenge_id": challenge_id,
        "questoes": questoes_list,
        "boss_hp": len(questoes_list),
        "tempo_limite": tempo_limite_min,
    }


@router.post("/challenge/{codigo}/answer")
def answer_challenge(
    codigo: str,
    challenge_id: int = Body(..., embed=True),
    questao_id: int = Body(..., embed=True),
    resposta: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Responde uma questão do desafio Boss Fight."""
    ensure_challenge_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    challenge = conn.execute("""
        SELECT * FROM study_room_challenges
        WHERE id = ? AND room_id = ? AND status = 'ativo'
    """, (challenge_id, room["id"])).fetchone()

    if not challenge:
        raise HTTPException(status_code=404, detail="Desafio não encontrado ou já finalizado")

    # Verificar resposta correta
    questao = conn.execute("""
        SELECT id, resposta FROM questoes WHERE id = ?
    """, (questao_id,)).fetchone()

    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    resposta_correta = questao["resposta"].strip().upper() if questao["resposta"] else ""
    resposta_usuario = resposta.strip().upper()
    acertou = resposta_usuario == resposta_correta

    boss_hp_atual = challenge["boss_hp_atual"]
    boss_hp_max = challenge["quantidade"]
    xp_ganho = 0

    if acertou:
        boss_hp_atual = max(0, boss_hp_atual - 1)
        xp_ganho = 10  # XP por acerto

        conn.execute("""
            UPDATE study_room_challenges SET boss_hp_atual = ? WHERE id = ?
        """, (boss_hp_atual, challenge_id))

    derrotado = boss_hp_atual <= 0
    if derrotado:
        conn.execute("""
            UPDATE study_room_challenges SET status = 'derrotado' WHERE id = ?
        """, (challenge_id,))
        xp_ganho += 50  # Bônus por derrotar o boss
        log.info(f"Boss defeated! User {user_id} completed challenge {challenge_id}")

    conn.commit()

    return {
        "acertou": acertou,
        "boss_hp_atual": boss_hp_atual,
        "boss_hp_max": boss_hp_max,
        "derrotado": derrotado,
        "xp_ganho": xp_ganho,
    }


# ============================================================
# 3. STREAK & CONSISTENCY REWARDS
# ============================================================


@router.get("/streak")
def get_streak(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna streak de dias consecutivos e multiplicador de XP."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    # Buscar datas distintas de participação do usuário em study rooms
    rows = conn.execute("""
        SELECT DISTINCT DATE(joined_at) as dia
        FROM study_room_participants
        WHERE user_id = ?
        ORDER BY dia DESC
    """, (user_id,)).fetchall()

    if not rows:
        return {
            "dias_consecutivos": 0,
            "multiplicador_xp": 1.0,
            "proximo_marco": 3,
            "historico_7dias": [],
        }

    # Calcular streak
    hoje = datetime.now().date()
    dias_unicos = []
    for r in rows:
        try:
            d = datetime.strptime(r["dia"], "%Y-%m-%d").date()
            dias_unicos.append(d)
        except (ValueError, TypeError):
            continue

    if not dias_unicos:
        return {
            "dias_consecutivos": 0,
            "multiplicador_xp": 1.0,
            "proximo_marco": 3,
            "historico_7dias": [],
        }

    dias_unicos.sort(reverse=True)

    # Verificar se hoje ou ontem está na lista (streak ainda ativo)
    streak = 0
    dia_esperado = hoje

    for d in dias_unicos:
        if d == dia_esperado:
            streak += 1
            dia_esperado = dia_esperado - timedelta(days=1)
        elif d == dia_esperado - timedelta(days=1):
            # Pulou um dia, mas conta o dia anterior
            dia_esperado = d
            streak += 1
            dia_esperado = dia_esperado - timedelta(days=1)
        elif d < dia_esperado:
            break

    # Se o último dia foi antes de ontem, streak = 0
    if dias_unicos[0] < hoje - timedelta(days=1):
        streak = 0

    # Multiplicador
    if streak >= 30:
        multiplicador = 3.0
    elif streak >= 14:
        multiplicador = 2.5
    elif streak >= 7:
        multiplicador = 2.0
    elif streak >= 3:
        multiplicador = 1.5
    else:
        multiplicador = 1.0

    # Próximo marco
    marcos = [3, 7, 14, 30]
    proximo_marco = None
    for m in marcos:
        if streak < m:
            proximo_marco = m
            break
    if proximo_marco is None:
        proximo_marco = streak + 30  # Próximo marco custom

    # Histórico últimos 7 dias
    historico_7dias = []
    for i in range(7):
        dia = hoje - timedelta(days=i)
        ativo = dia in dias_unicos
        historico_7dias.append({
            "dia": dia.isoformat(),
            "ativo": ativo,
        })

    return {
        "dias_consecutivos": streak,
        "multiplicador_xp": multiplicador,
        "proximo_marco": proximo_marco,
        "historico_7dias": historico_7dias,
    }


# ============================================================
# 4. PEER ACCOUNTABILITY NUDGE
# ============================================================


@router.post("/nudge/{codigo}/{target_user_id}")
def send_nudge(
    codigo: str,
    target_user_id: int,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Envia um nudge de incentivo para outro participante (rate limited: 1 a cada 5 min)."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    if user_id == target_user_id:
        raise HTTPException(status_code=400, detail="Você não pode enviar nudge para si mesmo")

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Verificar se ambos estão na sala
    sender_in_room = conn.execute("""
        SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?
    """, (room["id"], user_id)).fetchone()
    target_in_room = conn.execute("""
        SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?
    """, (room["id"], target_user_id)).fetchone()

    if not sender_in_room:
        raise HTTPException(status_code=403, detail="Você não está nesta sala")
    if not target_in_room:
        raise HTTPException(status_code=404, detail="Usuário alvo não está nesta sala")

    # Rate limit: verificar último nudge enviado pelo usuário nos últimos 5 min
    cinco_min_atras = (datetime.now() - timedelta(minutes=5)).isoformat()

    last_nudge = conn.execute("""
        SELECT id FROM study_room_chat
        WHERE room_id = ? AND user_id = ? AND mensagem LIKE '%[nudge]%' AND created_at > ?
    """, (room["id"], user_id, cinco_min_atras)).fetchone()

    if last_nudge:
        raise HTTPException(status_code=429, detail="Aguarde 5 minutos entre nudges")

    # Enviar mensagem de nudge no chat
    sender_name = get_user_name(conn, user_id)
    now = datetime.now().isoformat()
    mensagem = f"🔔 [nudge] {sender_name} te mandou um incentivo: De volta ao foco! 💪"

    conn.execute("""
        INSERT INTO study_room_chat (room_id, user_id, nome, mensagem, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (room["id"], user_id, "Sistema", mensagem, now))
    conn.commit()

    log.info(f"Nudge sent from user {user_id} to user {target_user_id} in room {codigo}")
    return {"ok": True, "mensagem": mensagem}

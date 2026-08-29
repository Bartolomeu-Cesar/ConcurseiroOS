"""Endpoints CRUD principais da Study Room: criar, entrar, status, chat, todo, histórico, minhas."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log

from .helpers import award_focus_xp, flush_focus_time, generate_code, get_user_name, is_focus_cycle
from .tables import ensure_studyroom_tables, run_studyroom_migrations

router = APIRouter(prefix="/api/studyroom", tags=["Study Room"])


# ============================================================
# ENDPOINTS
# ============================================================


@router.post("/criar")
def criar_sala(
    titulo: str = Body("Sala de Estudos"),
    max_participantes: int = Body(10),
    tecnica: str = Body("pomodoro"),
    duracao_min: int = Body(50),
    meta: str = Body(""),
    ciclo_foco_min: int = Body(25),
    ciclo_pausa_min: int = Body(5),
    ciclos_total: int = Body(4),
    pausa_longa_min: int = Body(15),
    modo_foco: bool = Body(False),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Cria uma nova sala de estudos."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    if tecnica not in ("pomodoro", "livre"):
        raise HTTPException(status_code=400, detail="Técnica deve ser 'pomodoro' ou 'livre'")
    if max_participantes < 2 or max_participantes > 50:
        raise HTTPException(status_code=400, detail="Máximo de participantes deve ser entre 2 e 50")
    if duracao_min < 5 or duracao_min > 240:
        raise HTTPException(status_code=400, detail="Duração deve ser entre 5 e 240 minutos")

    # Gera código único
    codigo = generate_code()
    while conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone():
        codigo = generate_code()

    now = datetime.now().isoformat()
    nome = get_user_name(conn, user_id)

    cursor = conn.execute("""
        INSERT INTO study_rooms (codigo, criador_id, titulo, max_participantes, tecnica, duracao_min,
                                 ciclo_foco_min, ciclo_pausa_min, ciclos_total, pausa_longa_min, modo_foco, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (codigo, user_id, titulo.strip() or "Sala de Estudos", max_participantes, tecnica, duracao_min,
          ciclo_foco_min, ciclo_pausa_min, ciclos_total, pausa_longa_min, int(modo_foco), now))
    room_id = cursor.lastrowid

    # Criador entra automaticamente
    conn.execute("""
        INSERT INTO study_room_participants (room_id, user_id, nome, status, ultimo_checkin, meta, joined_at)
        VALUES (?, ?, ?, 'focando', ?, ?, ?)
    """, (room_id, user_id, nome, now, meta.strip() if meta else "", now))
    conn.commit()

    log.info(f"Study room created: {codigo} by user {user_id}")
    return {
        "id": room_id,
        "codigo": codigo,
        "titulo": titulo.strip() or "Sala de Estudos",
        "max_participantes": max_participantes,
        "tecnica": tecnica,
        "duracao_min": duracao_min,
        "ciclo_foco_min": ciclo_foco_min,
        "ciclo_pausa_min": ciclo_pausa_min,
        "ciclos_total": ciclos_total,
        "pausa_longa_min": pausa_longa_min,
        "modo_foco": modo_foco,
        "criador_id": user_id,
        "created_at": now,
    }


@router.post("/entrar")
def entrar_sala(
    codigo: str = Body(...),
    meta: str = Body(""),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Entra em uma sala de estudos existente."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    codigo = codigo.strip().upper()
    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ? AND status = 'ativa'", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada ou inativa")

    # Verificar se já está na sala
    existing = conn.execute(
        "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if existing:
        # Update meta if provided
        if meta and meta.strip():
            conn.execute(
                "UPDATE study_room_participants SET meta = ? WHERE room_id = ? AND user_id = ?",
                (meta.strip(), room["id"], user_id)
            )
            conn.commit()
        return {"ok": True, "msg": "Já está na sala", "codigo": codigo}

    # Verificar limite de participantes
    count = conn.execute(
        "SELECT COUNT(*) as c FROM study_room_participants WHERE room_id = ?",
        (room["id"],)
    ).fetchone()["c"]
    if count >= room["max_participantes"]:
        raise HTTPException(status_code=400, detail="Sala cheia")

    now = datetime.now().isoformat()
    nome = get_user_name(conn, user_id)

    conn.execute("""
        INSERT INTO study_room_participants (room_id, user_id, nome, status, ultimo_checkin, meta, joined_at)
        VALUES (?, ?, ?, 'focando', ?, ?, ?)
    """, (room["id"], user_id, nome, now, meta.strip() if meta else "", now))
    conn.commit()

    log.info(f"User {user_id} joined study room {codigo}")
    return {"ok": True, "msg": f"Entrou na sala: {room['titulo']}", "codigo": codigo}


@router.get("/sala/{codigo}")
def status_sala(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna status atual da sala (polling endpoint)."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Participantes
    participants = conn.execute(
        "SELECT user_id, nome, status, tempo_estudado_seg, ultimo_checkin, meta, joined_at FROM study_room_participants WHERE room_id = ? ORDER BY joined_at",
        (room["id"],)
    ).fetchall()

    participantes = []
    for p in participants:
        participantes.append({
            "user_id": p["user_id"],
            "nome": p["nome"],
            "status": p["status"],
            "tempo_estudado": p["tempo_estudado_seg"],
            "ultimo_checkin": p["ultimo_checkin"],
            "meta": p["meta"] if p["meta"] else "",
            "is_me": p["user_id"] == user_id,
        })

    # Chat (últimas 50 mensagens)
    messages = conn.execute(
        "SELECT user_id, nome, mensagem, created_at FROM study_room_chat WHERE room_id = ? ORDER BY id DESC LIMIT 50",
        (room["id"],)
    ).fetchall()
    chat_messages = [
        {"user_id": m["user_id"], "nome": m["nome"], "mensagem": m["mensagem"], "created_at": m["created_at"]}
        for m in reversed(messages)
    ]

    # Todos
    todos_rows = conn.execute(
        "SELECT id, user_id, texto, completo, created_at FROM study_room_todos WHERE room_id = ? ORDER BY created_at",
        (room["id"],)
    ).fetchall()
    todos = [
        {"id": t["id"], "user_id": t["user_id"], "texto": t["texto"], "completo": bool(t["completo"]), "created_at": t["created_at"]}
        for t in todos_rows
    ]

    # Timer global: tempo desde criação da sala
    created = datetime.fromisoformat(room["created_at"])
    elapsed_sec = int((datetime.now() - created).total_seconds())

    # Pomodoro config
    ciclo_foco_min = room["ciclo_foco_min"] if "ciclo_foco_min" in room.keys() else 25
    ciclo_pausa_min = room["ciclo_pausa_min"] if "ciclo_pausa_min" in room.keys() else 5
    ciclos_total = room["ciclos_total"] if "ciclos_total" in room.keys() else 4
    pausa_longa_min = room["pausa_longa_min"] if "pausa_longa_min" in room.keys() else 15
    modo_foco = bool(room["modo_foco"]) if "modo_foco" in room.keys() else False

    return {
        "id": room["id"],
        "codigo": room["codigo"],
        "titulo": room["titulo"],
        "tecnica": room["tecnica"],
        "duracao_min": room["duracao_min"],
        "max_participantes": room["max_participantes"],
        "status": room["status"],
        "criador_id": room["criador_id"],
        "timer_global": elapsed_sec,
        "ciclo_foco_min": ciclo_foco_min,
        "ciclo_pausa_min": ciclo_pausa_min,
        "ciclos_total": ciclos_total,
        "pausa_longa_min": pausa_longa_min,
        "modo_foco": modo_foco,
        "created_at": room["created_at"],
        "participantes": participantes,
        "chat_messages": chat_messages,
        "todos": todos,
    }


@router.post("/status/{codigo}")
def atualizar_status(
    codigo: str,
    status: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Atualiza o status do participante na sala."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    if status not in ("focando", "pausando", "ausente"):
        raise HTTPException(status_code=400, detail="Status deve ser 'focando', 'pausando' ou 'ausente'")

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    participant = conn.execute(
        "SELECT id, status, ultimo_checkin, tempo_estudado_seg FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=404, detail="Você não está nesta sala")

    now = datetime.now().isoformat()

    # Se estava focando, acumula tempo estudado
    tempo_extra = 0
    if participant["status"] == "focando" and participant["ultimo_checkin"]:
        try:
            last = datetime.fromisoformat(participant["ultimo_checkin"])
            tempo_extra = int((datetime.now() - last).total_seconds())
        except (ValueError, TypeError):
            pass

    novo_tempo = participant["tempo_estudado_seg"] + tempo_extra

    # XP integration: when leaving focus mode, register and award XP
    xp_gained = 0
    if participant["status"] == "focando" and status != "focando" and tempo_extra > 0:
        xp_gained = award_focus_xp(conn, user_id, tempo_extra)

    conn.execute("""
        UPDATE study_room_participants
        SET status = ?, ultimo_checkin = ?, tempo_estudado_seg = ?
        WHERE room_id = ? AND user_id = ?
    """, (status, now, novo_tempo, room["id"], user_id))
    conn.commit()

    result = {"ok": True, "status": status, "tempo_estudado": novo_tempo}
    if xp_gained > 0:
        result["xp_gained"] = xp_gained
    return result


@router.post("/heartbeat/{codigo}")
def heartbeat(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Consolida periodicamente o tempo de foco sem alterar o status.

    Chamado pelo frontend em intervalos regulares enquanto o usuário está na
    sala. Garante que o tempo focado seja registrado em `sessoes_estudo`/
    `streaks` de forma incremental — assim, se o usuário fechar a aba sem
    clicar em "Sair", perde no máximo um intervalo de heartbeat em vez de toda
    a sessão.
    """
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    participant = conn.execute(
        "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=404, detail="Você não está nesta sala")

    flushed = flush_focus_time(conn, user_id, room["id"])

    result = {"ok": True, "tempo_estudado": flushed["tempo_estudado"]}
    if flushed["xp_gained"] > 0:
        result["xp_gained"] = flushed["xp_gained"]
    return result


@router.post("/sair/{codigo}")
def sair_sala(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Sai da sala consolidando o tempo de foco pendente.

    Diferente de `POST /status` com 'ausente', este endpoint sempre faz o
    flush final do tempo focado (mesmo que uma transição de status anterior
    já tenha ocorrido) e então marca o participante como 'ausente'. É o
    endpoint correto para o botão "Sair" e para o beforeunload da aba.
    """
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    participant = conn.execute(
        "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=404, detail="Você não está nesta sala")

    # Flush final do tempo focado pendente (se estava 'focando')
    flushed = flush_focus_time(conn, user_id, room["id"])

    # Marca como ausente
    conn.execute(
        "UPDATE study_room_participants SET status = 'ausente' WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    )
    conn.commit()

    result = {"ok": True, "status": "ausente", "tempo_estudado": flushed["tempo_estudado"]}
    if flushed["xp_gained"] > 0:
        result["xp_gained"] = flushed["xp_gained"]
    return result


@router.post("/chat/{codigo}")
def enviar_mensagem(
    codigo: str,
    mensagem: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Envia uma mensagem no chat da sala."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    if not mensagem or not mensagem.strip():
        raise HTTPException(status_code=400, detail="Mensagem vazia")
    if len(mensagem) > 500:
        raise HTTPException(status_code=400, detail="Mensagem muito longa (máx. 500 caracteres)")

    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Verificar se o usuário é participante
    participant = conn.execute(
        "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=403, detail="Você não é participante desta sala")

    # Focus mode: block chat during focus cycles
    modo_foco = bool(room["modo_foco"]) if "modo_foco" in room.keys() else False
    if modo_foco:
        created = datetime.fromisoformat(room["created_at"])
        elapsed_sec = int((datetime.now() - created).total_seconds())
        if is_focus_cycle(room, elapsed_sec):
            raise HTTPException(status_code=403, detail="Chat bloqueado durante ciclo de foco (modo foco ativo)")

    nome = get_user_name(conn, user_id)
    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_chat (room_id, user_id, nome, mensagem, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (room["id"], user_id, nome, mensagem.strip(), now))
    conn.commit()

    return {"ok": True, "mensagem": mensagem.strip(), "created_at": now}


@router.post("/todo/{codigo}")
def adicionar_todo(
    codigo: str,
    texto: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Adiciona uma tarefa ao todo list da sessão."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    if not texto or not texto.strip():
        raise HTTPException(status_code=400, detail="Texto da tarefa vazio")
    if len(texto) > 300:
        raise HTTPException(status_code=400, detail="Texto muito longo (máx. 300 caracteres)")

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Verificar se é participante
    participant = conn.execute(
        "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=403, detail="Você não é participante desta sala")

    now = datetime.now().isoformat()
    cursor = conn.execute("""
        INSERT INTO study_room_todos (room_id, user_id, texto, completo, created_at)
        VALUES (?, ?, ?, 0, ?)
    """, (room["id"], user_id, texto.strip(), now))
    conn.commit()

    return {"ok": True, "id": cursor.lastrowid, "texto": texto.strip(), "completo": False, "created_at": now}


@router.put("/todo/{codigo}/{todo_id}")
def atualizar_todo(
    codigo: str,
    todo_id: int,
    completo: bool = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Marca uma tarefa como completa ou incompleta."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Verificar se é participante
    participant = conn.execute(
        "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=403, detail="Você não é participante desta sala")

    todo = conn.execute(
        "SELECT id, room_id FROM study_room_todos WHERE id = ? AND room_id = ?",
        (todo_id, room["id"])
    ).fetchone()
    if not todo:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")

    conn.execute("UPDATE study_room_todos SET completo = ? WHERE id = ?", (int(completo), todo_id))
    conn.commit()

    return {"ok": True, "id": todo_id, "completo": completo}


@router.get("/historico")
def historico_sessoes(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna histórico de sessões com tempo total focado por sala."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    rows = conn.execute("""
        SELECT sr.id, sr.codigo, sr.titulo, sr.tecnica, sr.duracao_min, sr.created_at,
               srp.tempo_estudado_seg, srp.joined_at, srp.meta
        FROM study_rooms sr
        INNER JOIN study_room_participants srp ON srp.room_id = sr.id
        WHERE srp.user_id = ?
        ORDER BY sr.created_at DESC
        LIMIT 50
    """, (user_id,)).fetchall()

    historico = []
    for r in rows:
        historico.append({
            "id": r["id"],
            "codigo": r["codigo"],
            "titulo": r["titulo"],
            "tecnica": r["tecnica"],
            "duracao_min": r["duracao_min"],
            "tempo_focado_seg": r["tempo_estudado_seg"],
            "tempo_focado_min": round(r["tempo_estudado_seg"] / 60, 1) if r["tempo_estudado_seg"] else 0,
            "meta": r["meta"] if r["meta"] else "",
            "joined_at": r["joined_at"],
            "created_at": r["created_at"],
        })

    return {"historico": historico}


@router.get("/minhas")
def minhas_salas(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Lista as salas do usuário (que participa ou criou)."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)

    rows = conn.execute("""
        SELECT sr.id, sr.codigo, sr.titulo, sr.tecnica, sr.duracao_min,
               sr.max_participantes, sr.status, sr.created_at, sr.criador_id,
               (SELECT COUNT(*) FROM study_room_participants WHERE room_id = sr.id) as num_participantes
        FROM study_rooms sr
        INNER JOIN study_room_participants srp ON srp.room_id = sr.id
        WHERE srp.user_id = ?
        ORDER BY sr.created_at DESC
        LIMIT 20
    """, (user_id,)).fetchall()

    salas = []
    for r in rows:
        salas.append({
            "id": r["id"],
            "codigo": r["codigo"],
            "titulo": r["titulo"],
            "tecnica": r["tecnica"],
            "duracao_min": r["duracao_min"],
            "max_participantes": r["max_participantes"],
            "num_participantes": r["num_participantes"],
            "status": r["status"],
            "criador_id": r["criador_id"],
            "is_owner": r["criador_id"] == user_id,
            "created_at": r["created_at"],
        })

    return {"salas": salas}

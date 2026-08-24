"""
Router de Study Room — Sala de Estudos Virtual com Timer Compartilhado.
Suporta técnicas Pomodoro e Livre, chat em tempo real via polling.
Inclui: meta/goal, todo list, XP integration, histórico, pomodoro cycles, modo foco.
"""
import random
import string
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from logger import log

router = APIRouter(prefix="/api/studyroom", tags=["Study Room"])


# ============================================================
# TABELAS
# ============================================================

def _ensure_studyroom_tables(conn):
    """Cria tabelas de study room se não existirem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            criador_id INTEGER NOT NULL,
            titulo TEXT DEFAULT 'Sala de Estudos',
            max_participantes INTEGER DEFAULT 10,
            tecnica TEXT DEFAULT 'pomodoro',
            duracao_min INTEGER DEFAULT 50,
            status TEXT DEFAULT 'ativa',
            ciclo_foco_min INTEGER DEFAULT 25,
            ciclo_pausa_min INTEGER DEFAULT 5,
            ciclos_total INTEGER DEFAULT 4,
            pausa_longa_min INTEGER DEFAULT 15,
            modo_foco INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT 'Estudante',
            status TEXT DEFAULT 'focando',
            tempo_estudado_seg INTEGER DEFAULT 0,
            ultimo_checkin TEXT DEFAULT '',
            meta TEXT DEFAULT '',
            joined_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT 'Estudante',
            mensagem TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            texto TEXT NOT NULL,
            completo INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_rooms_codigo ON study_rooms(codigo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_participants_room ON study_room_participants(room_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_chat_room ON study_room_chat(room_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_todos_room ON study_room_todos(room_id)")
    conn.commit()


def _run_studyroom_migrations(conn):
    """Adiciona colunas novas às tabelas existentes (idempotente)."""
    migrations = [
        ("study_room_participants", "meta", "ALTER TABLE study_room_participants ADD COLUMN meta TEXT DEFAULT ''"),
        ("study_rooms", "ciclo_foco_min", "ALTER TABLE study_rooms ADD COLUMN ciclo_foco_min INTEGER DEFAULT 25"),
        ("study_rooms", "ciclo_pausa_min", "ALTER TABLE study_rooms ADD COLUMN ciclo_pausa_min INTEGER DEFAULT 5"),
        ("study_rooms", "ciclos_total", "ALTER TABLE study_rooms ADD COLUMN ciclos_total INTEGER DEFAULT 4"),
        ("study_rooms", "pausa_longa_min", "ALTER TABLE study_rooms ADD COLUMN pausa_longa_min INTEGER DEFAULT 15"),
        ("study_rooms", "modo_foco", "ALTER TABLE study_rooms ADD COLUMN modo_foco INTEGER DEFAULT 0"),
    ]
    for _table, _col, sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # Column already exists


def _generate_code(length=6):
    """Gera um código alfanumérico único para a sala."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))


def _get_user_name(conn, user_id: int) -> str:
    """Busca o nome do usuário pelo ID."""
    row = conn.execute("SELECT nome, username FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        return row["nome"] or row["username"] or f"Estudante #{user_id}"
    return f"Estudante #{user_id}"


def _is_focus_cycle(room, elapsed_sec: int) -> bool:
    """Determina se o momento atual é ciclo de foco baseado no pomodoro config."""
    ciclo_foco = room["ciclo_foco_min"] * 60
    ciclo_pausa = room["ciclo_pausa_min"] * 60
    ciclos_total = room["ciclos_total"]
    pausa_longa = room["pausa_longa_min"] * 60

    # Duração de um ciclo completo (foco + pausa)
    ciclo_completo = ciclo_foco + ciclo_pausa
    # Duração de um round completo (N ciclos + pausa longa)
    round_completo = ciclos_total * ciclo_completo - ciclo_pausa + pausa_longa

    # Posição dentro do round
    pos_round = elapsed_sec % round_completo

    # Verificar se estamos na pausa longa
    if pos_round >= ciclos_total * ciclo_completo - ciclo_pausa:
        return False  # Pausa longa

    # Verificar dentro do ciclo normal
    pos_ciclo = pos_round % ciclo_completo
    return pos_ciclo < ciclo_foco


def _award_focus_xp(conn, user_id: int, tempo_foco_seg: int):
    """Registra sessão de estudo e calcula XP por tempo focado.
    XP: 20 por hora de foco (proporcional).
    """
    if tempo_foco_seg <= 0:
        return 0

    horas = tempo_foco_seg / 3600.0
    hoje = datetime.now().strftime("%Y-%m-%d")

    # Registrar em sessoes_estudo (tipo='studyroom')
    try:
        existing = conn.execute(
            "SELECT id, horas FROM sessoes_estudo WHERE data = ? AND tipo = 'studyroom' AND user_id = ?",
            (hoje, user_id)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE sessoes_estudo SET horas = horas + ? WHERE id = ?",
                (round(horas, 4), existing["id"])
            )
        else:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'studyroom', ?)",
                ("Study Room", round(horas, 4), hoje, user_id)
            )
    except Exception:
        # sessoes_estudo table may not have user_id column in some setups
        try:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo) VALUES (?, ?, ?, 'studyroom')",
                ("Study Room", round(horas, 4), hoje)
            )
        except Exception:
            pass

    xp_gained = int(20 * horas)
    return xp_gained


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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

    if tecnica not in ("pomodoro", "livre"):
        raise HTTPException(status_code=400, detail="Técnica deve ser 'pomodoro' ou 'livre'")
    if max_participantes < 2 or max_participantes > 50:
        raise HTTPException(status_code=400, detail="Máximo de participantes deve ser entre 2 e 50")
    if duracao_min < 5 or duracao_min > 240:
        raise HTTPException(status_code=400, detail="Duração deve ser entre 5 e 240 minutos")

    # Gera código único
    codigo = _generate_code()
    while conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone():
        codigo = _generate_code()

    now = datetime.now().isoformat()
    nome = _get_user_name(conn, user_id)

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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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
    nome = _get_user_name(conn, user_id)

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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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
        xp_gained = _award_focus_xp(conn, user_id, tempo_extra)

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


@router.post("/chat/{codigo}")
def enviar_mensagem(
    codigo: str,
    mensagem: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Envia uma mensagem no chat da sala."""
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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
        if _is_focus_cycle(room, elapsed_sec):
            raise HTTPException(status_code=403, detail="Chat bloqueado durante ciclo de foco (modo foco ativo)")

    nome = _get_user_name(conn, user_id)
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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)

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


# ============================================================
# MICRO-RETRIEVAL: Break Cards (mostrar flashcards/súmulas na pausa)
# ============================================================


@router.get("/break-cards")
def get_break_cards(
    quantidade: int = 5,
    materia: str = "",
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna 3-5 cards para micro-retrieval durante pausas do Pomodoro.

    Seleciona itens com base nas técnicas de estudo:
    - Prioriza itens com recall baixo (quase esquecendo)
    - Mistura flashcards + súmulas para variação (contextual interference)
    - Prefere itens da matéria da sessão atual (se definida)
    - Limita a 5 para não sobrecarregar a pausa (5min)
    """
    from study_ordering import order_items_intelligently
    from utils import today_str

    quantidade = min(quantidade, 5)  # Máx 5 na pausa
    hoje = today_str()

    # === Buscar flashcards pendentes ===
    fc_query = """
        SELECT id, pergunta, resposta, intervalo_dias, easiness_factor, repetitions, materia,
               'flashcard' as tipo
        FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?
    """
    fc_params = [hoje, user_id]
    if materia:
        fc_query += " AND materia = ?"
        fc_params.append(materia)
    fc_query += " LIMIT 20"
    flashcards = [dict(r) for r in conn.execute(fc_query, fc_params).fetchall()]

    # === Buscar súmulas pendentes ===
    sm_query = """
        SELECT id, tribunal, numero, enunciado, tema, vinculante,
               intervalo_dias, easiness_factor, repetitions,
               'sumula' as tipo
        FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?
    """
    sm_params = [hoje, user_id]
    if materia:
        sm_query += " AND tema = ?"
        sm_params.append(materia)
    sm_query += " LIMIT 20"
    sumulas = [dict(r) for r in conn.execute(sm_query, sm_params).fetchall()]

    # === Combinar e ordenar com técnicas de estudo ===
    all_items = flashcards + sumulas

    if not all_items:
        # Fallback: buscar flashcards/súmulas aleatórias (mesmo que não pendentes)
        fallback_fc = conn.execute(
            "SELECT id, pergunta, resposta, intervalo_dias, easiness_factor, repetitions, materia, 'flashcard' as tipo FROM flashcards WHERE user_id = ? ORDER BY RANDOM() LIMIT ?",
            (user_id, quantidade)
        ).fetchall()
        all_items = [dict(r) for r in fallback_fc]

    if not all_items:
        return {"cards": [], "total_pendentes": 0}

    # Usar ordering inteligente
    ordered = order_items_intelligently(
        all_items,
        materia_key="materia",
    )

    # Limpar campos internos e pegar apenas a quantidade pedida
    cards = []
    for item in ordered[:quantidade]:
        item.pop("_expanding_retrieval", None)
        cards.append(item)

    # Total pendentes (para mostrar "X restantes")
    total_pendentes = len(flashcards) + len(sumulas)

    return {
        "cards": cards,
        "total_pendentes": total_pendentes,
        "tecnicas_ativas": ["micro-retrieval", "interleaving", "desirable-difficulty"],
    }


# ============================================================
# SESSION SUMMARY: Métricas pós-sessão
# ============================================================


@router.get("/session-summary/{codigo}")
def get_session_summary(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna resumo completo da sessão de estudo ao sair da sala.

    Métricas: tempo focado, ciclos completados, cards revisados,
    comparação com meta, XP ganho, sugestões para próxima sessão.
    """
    _ensure_studyroom_tables(conn)
    _run_studyroom_migrations(conn)
    from utils import today_str

    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    participant = conn.execute(
        "SELECT * FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=404, detail="Participante não encontrado")

    # Calcular tempo focado (inclui tempo desde último checkin se ainda focando)
    tempo_total = participant["tempo_estudado_seg"] or 0
    if participant["status"] == "focando" and participant["ultimo_checkin"]:
        try:
            last = datetime.fromisoformat(participant["ultimo_checkin"])
            tempo_total += int((datetime.now() - last).total_seconds())
        except (ValueError, TypeError):
            pass

    # Calcular ciclos completados
    ciclo_foco = (room.get("ciclo_foco_min") or 25) * 60
    ciclo_pausa = (room.get("ciclo_pausa_min") or 5) * 60
    ciclo_completo = ciclo_foco + ciclo_pausa
    ciclos_completados = tempo_total // ciclo_completo if ciclo_completo > 0 else 0

    # Buscar cards revisados hoje
    hoje = today_str()
    flashcards_revisados = conn.execute(
        "SELECT COALESCE(flashcards_revisados, 0) FROM streaks WHERE data = ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()
    flashcards_revisados = flashcards_revisados[0] if flashcards_revisados else 0

    sumulas_revisadas = conn.execute(
        "SELECT COALESCE(sumulas_revisadas, 0) FROM streaks WHERE data = ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()
    sumulas_revisadas = sumulas_revisadas[0] if sumulas_revisadas else 0

    questoes_resolvidas = conn.execute(
        "SELECT COALESCE(questoes_resolvidas, 0) FROM streaks WHERE data = ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()
    questoes_resolvidas = questoes_resolvidas[0] if questoes_resolvidas else 0

    # Meta da sessão
    meta = participant["meta"] if participant.get("meta") else ""
    meta_cumprida = bool(meta and tempo_total > 0)  # Simplificado; ideally check specific goal

    # XP estimado
    horas = tempo_total / 3600.0
    xp_ganho = int(20 * horas)

    # Ranking na sala
    all_participants = conn.execute(
        "SELECT user_id, nome, tempo_estudado_seg FROM study_room_participants WHERE room_id = ? ORDER BY tempo_estudado_seg DESC",
        (room["id"],)
    ).fetchall()
    ranking_pos = 1
    for i, p in enumerate(all_participants):
        if p["user_id"] == user_id:
            ranking_pos = i + 1
            break

    # Sugestões para próxima sessão
    sugestoes = []
    if tempo_total < 25 * 60:
        sugestoes.append("💡 Tente completar ao menos 1 ciclo Pomodoro (25min) na próxima vez")
    if flashcards_revisados == 0:
        sugestoes.append("🃏 Aproveite as pausas para revisar flashcards pendentes")
    if ciclos_completados >= 4:
        sugestoes.append("🎯 Excelente! Experimente aumentar para 30min de foco no próximo ciclo")

    # Pendentes restantes
    pendentes_flashcards = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()[0]
    pendentes_sumulas = conn.execute(
        "SELECT COUNT(*) FROM sumulas WHERE proxima_revisao <= ? AND user_id = ?",
        (hoje, user_id)
    ).fetchone()[0]

    return {
        "sessao": {
            "titulo": room["titulo"],
            "tecnica": room["tecnica"],
            "codigo": room["codigo"],
            "tempo_focado_seg": tempo_total,
            "tempo_focado_min": round(tempo_total / 60, 1),
            "ciclos_completados": ciclos_completados,
            "ciclos_total": room.get("ciclos_total") or 4,
        },
        "progresso": {
            "flashcards_revisados": flashcards_revisados,
            "sumulas_revisadas": sumulas_revisadas,
            "questoes_resolvidas": questoes_resolvidas,
            "xp_ganho": xp_ganho,
            "ranking_posicao": ranking_pos,
            "total_participantes": len(all_participants),
        },
        "meta": {
            "texto": meta,
            "cumprida": meta_cumprida,
        },
        "pendentes": {
            "flashcards": pendentes_flashcards,
            "sumulas": pendentes_sumulas,
        },
        "sugestoes": sugestoes,
    }


# ============================================================
# GOAL SUGGESTION: Meta SMART vinculada ao edital + ROI
# ============================================================


@router.get("/goal-suggestion")
def get_goal_suggestion(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Sugere uma meta SMART para a sessão baseada no ROI das matérias do edital.

    Analisa: peso da banca × gap de acertos / horas investidas
    Retorna: matéria sugerida + quantidade específica + justificativa.
    """
    from utils import today_str

    hoje = today_str()

    # 1. Buscar matérias do edital ativo
    materias_edital = conn.execute(
        "SELECT DISTINCT materia FROM edital WHERE user_id = ? AND arquivado = 0",
        (user_id,)
    ).fetchall()
    materias_edital = [r[0] for r in materias_edital]

    # 2. Calcular ROI por matéria
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes WHERE user_id = ?", (user_id,)).fetchone()[0] or 1

    resultados = []
    for materia in materias_edital:
        # Peso na banca (% de questões)
        qtd_mat = conn.execute(
            "SELECT COUNT(*) FROM questoes WHERE materia = ? AND user_id = ?",
            (materia, user_id)
        ).fetchone()[0]
        peso = round(qtd_mat / total_questoes * 100, 1) if total_questoes > 0 else 0

        # Acertos
        acertos = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
            WHERE q.materia = ? AND qr.user_id = ?
        """, (materia, user_id)).fetchone()
        pct_acerto = round((acertos["acertos"] / acertos["total"]) * 100, 1) if acertos["total"] > 0 else 0
        gap = 100 - pct_acerto

        # Horas investidas
        horas = conn.execute(
            "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ? AND user_id = ?",
            (materia, user_id)
        ).fetchone()[0]

        # Pendentes hoje (flashcards + súmulas)
        fc_pendentes = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE materia = ? AND proxima_revisao <= ? AND user_id = ?",
            (materia, hoje, user_id)
        ).fetchone()[0]
        sm_pendentes = conn.execute(
            "SELECT COUNT(*) FROM sumulas WHERE tema = ? AND proxima_revisao <= ? AND user_id = ?",
            (materia, hoje, user_id)
        ).fetchone()[0]

        roi = round((peso * gap) / (horas + 1), 2)

        resultados.append({
            "materia": materia,
            "peso_banca": peso,
            "pct_acerto": pct_acerto,
            "gap": gap,
            "horas_investidas": round(horas, 1),
            "roi": roi,
            "pendentes_flashcards": fc_pendentes,
            "pendentes_sumulas": sm_pendentes,
        })

    if not resultados:
        return {
            "sugestao": None,
            "motivo": "Nenhuma matéria no edital. Cadastre seu edital primeiro.",
        }

    # Ordenar por ROI descendente
    resultados.sort(key=lambda x: x["roi"], reverse=True)
    top = resultados[0]

    # Gerar meta SMART
    atividades = []
    if top["pendentes_flashcards"] > 0:
        fc_qty = min(top["pendentes_flashcards"], 15)
        atividades.append(f"Revisar {fc_qty} flashcards de {top['materia']}")
    if top["pendentes_sumulas"] > 0:
        sm_qty = min(top["pendentes_sumulas"], 10)
        atividades.append(f"Revisar {sm_qty} súmulas de {top['materia']}")
    if top["gap"] > 30:
        atividades.append(f"Resolver 10 questões de {top['materia']}")

    if not atividades:
        atividades.append(f"Estudar {top['materia']} por 25 minutos (1 Pomodoro)")

    meta_texto = atividades[0]  # Principal sugestão

    return {
        "sugestao": {
            "meta": meta_texto,
            "materia": top["materia"],
            "roi": top["roi"],
            "peso_banca": top["peso_banca"],
            "gap": top["gap"],
            "atividades_sugeridas": atividades,
        },
        "alternativas": [
            {"meta": a, "materia": top["materia"]}
            for a in atividades[1:]
        ],
        "top_materias_roi": resultados[:3],
        "motivo": f"{top['materia']} tem maior ROI: peso {top['peso_banca']}% na banca com {top['gap']}% de gap",
    }


# ============================================================
# TABELAS ADICIONAIS
# ============================================================

def _ensure_commitment_tables(conn):
    """Cria tabela de commitments se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT '',
            commitment TEXT NOT NULL,
            xp_stake INTEGER DEFAULT 50,
            cumprida INTEGER DEFAULT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def _ensure_intention_tables(conn):
    """Cria tabela de intentions se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_intentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            intencao TEXT NOT NULL,
            como_vou_estudar TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def _ensure_reflection_tables(conn):
    """Cria tabela de reflections se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            o_que_aprendi TEXT NOT NULL,
            o_que_foi_dificil TEXT NOT NULL,
            proximo_passo TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def _ensure_challenge_tables(conn):
    """Cria tabela de challenges se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            materia TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            tempo_limite_min INTEGER DEFAULT 15,
            boss_hp_atual INTEGER NOT NULL,
            status TEXT DEFAULT 'ativo',
            questoes_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def _ensure_discussion_tables(conn):
    """Cria tabelas de discussions se não existirem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_discussions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            questao_id INTEGER,
            enunciado TEXT NOT NULL,
            alternativas_json TEXT,
            resposta_correta TEXT,
            materia TEXT DEFAULT '',
            status TEXT DEFAULT 'aberta',
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_discussion_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT '',
            resposta TEXT NOT NULL,
            justificativa TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (discussion_id) REFERENCES study_room_discussions(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_discussion_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_id INTEGER NOT NULL,
            response_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT '',
            comentario TEXT NOT NULL,
            concordo INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (discussion_id) REFERENCES study_room_discussions(id),
            FOREIGN KEY (response_id) REFERENCES study_room_discussion_responses(id)
        )
    """)
    conn.commit()


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
    _ensure_commitment_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    if not commitment or not commitment.strip():
        raise HTTPException(status_code=400, detail="Commitment não pode ser vazio")

    if xp_stake < 0 or xp_stake > 500:
        raise HTTPException(status_code=400, detail="XP stake deve ser entre 0 e 500")

    nome = _get_user_name(conn, user_id)
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
    _ensure_commitment_tables(conn)

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
    _ensure_commitment_tables(conn)

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
# 2. ELABORATIVE INTERROGATION PROMPTS
# ============================================================

ELABORATION_PROMPTS = [
    {"prompt": "Por que esse conceito funciona dessa forma?", "tipo": "causal", "ciclo_sugerido": "foco"},
    {"prompt": "Como isso se conecta com o que você já sabe?", "tipo": "conexão", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual seria um exemplo prático disso?", "tipo": "aplicação", "ciclo_sugerido": "foco"},
    {"prompt": "Se tivesse que explicar para alguém, como faria?", "tipo": "ensino", "ciclo_sugerido": "pausa"},
    {"prompt": "O que aconteceria se o contrário fosse verdade?", "tipo": "contra-factual", "ciclo_sugerido": "foco"},
    {"prompt": "Quais são as exceções ou limitações desse conceito?", "tipo": "crítica", "ciclo_sugerido": "foco"},
    {"prompt": "Como esse tema aparece em provas anteriores?", "tipo": "aplicação", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual a diferença entre esse conceito e outros semelhantes?", "tipo": "comparação", "ciclo_sugerido": "foco"},
    {"prompt": "Que analogia você usaria para explicar isso?", "tipo": "analogia", "ciclo_sugerido": "pausa"},
    {"prompt": "Quais são as consequências práticas de não entender isso?", "tipo": "consequência", "ciclo_sugerido": "foco"},
    {"prompt": "Como você resumiria isso em uma frase?", "tipo": "síntese", "ciclo_sugerido": "pausa"},
    {"prompt": "Que pergunta você faria a um professor sobre isso?", "tipo": "curiosidade", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual a relação entre esse conceito e a questão que errei antes?", "tipo": "conexão", "ciclo_sugerido": "foco"},
    {"prompt": "Se fosse cair na prova, como seria a questão?", "tipo": "simulação", "ciclo_sugerido": "foco"},
    {"prompt": "O que eu ainda não entendi completamente sobre isso?", "tipo": "metacognição", "ciclo_sugerido": "pausa"},
    {"prompt": "Como eu poderia desenhar ou esquematizar esse conceito?", "tipo": "visual", "ciclo_sugerido": "pausa"},
    {"prompt": "Qual a origem histórica ou lógica desse princípio?", "tipo": "fundamento", "ciclo_sugerido": "foco"},
    {"prompt": "Quais palavras-chave são essenciais para lembrar?", "tipo": "memorização", "ciclo_sugerido": "foco"},
    {"prompt": "Como esse assunto se relaciona com casos reais ou jurisprudência?", "tipo": "aplicação", "ciclo_sugerido": "foco"},
    {"prompt": "Se eu esquecesse tudo amanhã, qual seria o ponto central a reter?", "tipo": "essência", "ciclo_sugerido": "pausa"},
]


@router.get("/elaboration-prompt")
def get_elaboration_prompt(
    user_id: int = Depends(get_user_id),
):
    """Retorna uma pergunta metacognitiva aleatória para interrogação elaborativa."""
    prompt = random.choice(ELABORATION_PROMPTS)
    return prompt


# ============================================================
# 3. FOCUS SCORE
# ============================================================


@router.get("/focus-score/{codigo}")
def get_focus_score(
    codigo: str,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Calcula score de foco 0-100 baseado em múltiplos fatores."""
    _ensure_studyroom_tables(conn)
    _ensure_commitment_tables(conn)

    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    participant = conn.execute("""
        SELECT * FROM study_room_participants
        WHERE room_id = ? AND user_id = ?
    """, (room["id"], user_id)).fetchone()

    if not participant:
        raise HTTPException(status_code=404, detail="Você não está nesta sala")

    # 1. pct_tempo_focando (40%) — % do tempo na sala em status 'focando'
    tempo_estudado = participant["tempo_estudado_seg"] or 0
    room_created = datetime.fromisoformat(room["created_at"])
    elapsed_total = (datetime.now() - room_created).total_seconds()
    if elapsed_total > 0:
        pct_foco = min(tempo_estudado / max(elapsed_total, 1), 1.0)
    else:
        pct_foco = 0.0
    score_foco = pct_foco * 40

    # 2. ciclos_completos (20%) — baseado no número esperado vs realizado
    ciclo_foco_seg = room["ciclo_foco_min"] * 60
    ciclos_esperados = max(elapsed_total / (ciclo_foco_seg + room["ciclo_pausa_min"] * 60), 1)
    ciclos_realizados = tempo_estudado / ciclo_foco_seg if ciclo_foco_seg > 0 else 0
    pct_ciclos = min(ciclos_realizados / ciclos_esperados, 1.0)
    score_ciclos = pct_ciclos * 20

    # 3. cards_revisados_pausa (20%) — check break cards viewed
    try:
        cards_count = conn.execute("""
            SELECT COUNT(*) as cnt FROM study_room_chat
            WHERE room_id = ? AND user_id = ? AND mensagem LIKE '%[break-card]%'
        """, (room["id"], user_id)).fetchone()
        cards_revisados = cards_count["cnt"] if cards_count else 0
    except Exception:
        cards_revisados = 0
    pct_cards = min(cards_revisados / max(ciclos_realizados, 1), 1.0)
    score_cards = pct_cards * 20

    # 4. meta_definida (10%) — se tem meta/goal definida
    meta = participant["meta"] if participant["meta"] else ""
    score_meta = 10 if meta.strip() else 0

    # 5. commitment_cumprido (10%) — se tem commitment resolvido positivamente
    commitment_ok = conn.execute("""
        SELECT COUNT(*) as cnt FROM study_room_commitments
        WHERE room_id = ? AND user_id = ? AND cumprida = 1
    """, (room["id"], user_id)).fetchone()
    has_commitment_ok = (commitment_ok["cnt"] if commitment_ok else 0) > 0
    score_commitment = 10 if has_commitment_ok else 0

    # Score total
    score = int(score_foco + score_ciclos + score_cards + score_meta + score_commitment)
    score = max(0, min(100, score))

    # Nível
    if score >= 90:
        nivel = "lendário"
    elif score >= 70:
        nivel = "mestre"
    elif score >= 40:
        nivel = "focado"
    else:
        nivel = "iniciante"

    # Dicas
    dicas = []
    if pct_foco < 0.5:
        dicas.append("Tente manter o foco por períodos mais longos sem interrupção.")
    if not meta.strip():
        dicas.append("Defina uma meta para a sessão — ajuda na direção do estudo.")
    if cards_revisados == 0:
        dicas.append("Aproveite as pausas para revisar flashcards e consolidar o aprendizado.")
    if not has_commitment_ok:
        dicas.append("Faça um commitment público para aumentar sua responsabilidade.")
    if pct_ciclos < 0.5:
        dicas.append("Complete ciclos inteiros de Pomodoro para maximizar retenção.")

    return {
        "score": score,
        "breakdown": {
            "pct_tempo_focando": round(score_foco, 1),
            "ciclos_completos": round(score_ciclos, 1),
            "cards_revisados_pausa": round(score_cards, 1),
            "meta_definida": round(score_meta, 1),
            "commitment_cumprido": round(score_commitment, 1),
        },
        "nivel": nivel,
        "dicas": dicas,
    }


# ============================================================
# 4. SESSION INTENTION + REFLECTION
# ============================================================


@router.post("/intention/{codigo}")
def criar_intention(
    codigo: str,
    intencao: str = Body(..., embed=True),
    como_vou_estudar: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Salva intenção de início de sessão."""
    _ensure_intention_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    if not intencao or not intencao.strip():
        raise HTTPException(status_code=400, detail="Intenção não pode ser vazia")
    if not como_vou_estudar or not como_vou_estudar.strip():
        raise HTTPException(status_code=400, detail="'Como vou estudar' não pode ser vazio")

    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_intentions (room_id, user_id, intencao, como_vou_estudar, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (room["id"], user_id, intencao.strip(), como_vou_estudar.strip(), now))
    conn.commit()

    log.info(f"Intention saved by user {user_id} in room {codigo}")
    return {"ok": True, "intencao": intencao.strip(), "como_vou_estudar": como_vou_estudar.strip()}


@router.post("/reflection/{codigo}")
def criar_reflection(
    codigo: str,
    o_que_aprendi: str = Body(..., embed=True),
    o_que_foi_dificil: str = Body(..., embed=True),
    proximo_passo: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Salva reflexão de fim de sessão."""
    _ensure_reflection_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    if not o_que_aprendi or not o_que_aprendi.strip():
        raise HTTPException(status_code=400, detail="'O que aprendi' não pode ser vazio")
    if not o_que_foi_dificil or not o_que_foi_dificil.strip():
        raise HTTPException(status_code=400, detail="'O que foi difícil' não pode ser vazio")
    if not proximo_passo or not proximo_passo.strip():
        raise HTTPException(status_code=400, detail="'Próximo passo' não pode ser vazio")

    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_reflections (room_id, user_id, o_que_aprendi, o_que_foi_dificil, proximo_passo, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (room["id"], user_id, o_que_aprendi.strip(), o_que_foi_dificil.strip(), proximo_passo.strip(), now))
    conn.commit()

    log.info(f"Reflection saved by user {user_id} in room {codigo}")
    return {
        "ok": True,
        "o_que_aprendi": o_que_aprendi.strip(),
        "o_que_foi_dificil": o_que_foi_dificil.strip(),
        "proximo_passo": proximo_passo.strip(),
    }


@router.get("/reflections")
def listar_reflections(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna as últimas 10 reflexões do usuário."""
    _ensure_reflection_tables(conn)

    rows = conn.execute("""
        SELECT r.id, r.o_que_aprendi, r.o_que_foi_dificil, r.proximo_passo, r.created_at,
               s.codigo, s.titulo
        FROM study_room_reflections r
        JOIN study_rooms s ON s.id = r.room_id
        WHERE r.user_id = ?
        ORDER BY r.created_at DESC
        LIMIT 10
    """, (user_id,)).fetchall()

    return {
        "reflections": [
            {
                "id": r["id"],
                "o_que_aprendi": r["o_que_aprendi"],
                "o_que_foi_dificil": r["o_que_foi_dificil"],
                "proximo_passo": r["proximo_passo"],
                "sala_codigo": r["codigo"],
                "sala_titulo": r["titulo"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


# ============================================================
# 5. STREAK & CONSISTENCY REWARDS
# ============================================================


@router.get("/streak")
def get_streak(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Retorna streak de dias consecutivos e multiplicador de XP."""
    _ensure_studyroom_tables(conn)

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
    from datetime import timedelta
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
# 6. GUIDED MINDFULNESS BREAK
# ============================================================


@router.get("/mindfulness")
def get_mindfulness_exercise(
    user_id: int = Depends(get_user_id),
):
    """Retorna um exercício guiado de respiração para pausa mindfulness."""
    mensagens_motivacionais = [
        "Você está no caminho certo. Cada minuto de estudo te aproxima do objetivo. 🌟",
        "A consistência vence o talento. Continue firme! 💪",
        "Respire fundo. Você está investindo no seu futuro. 🎯",
        "Sua dedicação já te diferencia. Orgulhe-se do esforço! 🏆",
        "Lembre-se: descanso inteligente faz parte da alta performance. 🧠",
        "Você já provou que consegue. Agora é só manter. 🚀",
    ]

    # 8 ciclos de respiração: Inspire 4s, Segure 4s, Expire 6s = 14s por ciclo
    passos = []
    for i in range(8):
        passos.append({"instrucao": "Inspire profundamente pelo nariz... 🌬️", "duracao_seg": 4})
        passos.append({"instrucao": "Segure o ar suavemente... ⏸️", "duracao_seg": 4})
        passos.append({"instrucao": "Expire lentamente pela boca... 💨", "duracao_seg": 6})

    # Adicionar mensagem final
    passos.append({"instrucao": "Exercício completo. Você está pronto para voltar ao foco! ✅", "duracao_seg": 8})

    return {
        "duracao_seg": 120,
        "passos": passos,
        "mensagem_motivacional": random.choice(mensagens_motivacionais),
    }


# ============================================================
# 7. CHALLENGE MODE (BOSS FIGHT)
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
    _ensure_challenge_tables(conn)

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

    import json

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
    _ensure_challenge_tables(conn)

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
# 8. PEER ACCOUNTABILITY NUDGE
# ============================================================


@router.post("/nudge/{codigo}/{target_user_id}")
def send_nudge(
    codigo: str,
    target_user_id: int,
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Envia um nudge de incentivo para outro participante (rate limited: 1 a cada 5 min)."""
    _ensure_studyroom_tables(conn)

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
    from datetime import timedelta
    cinco_min_atras = (datetime.now() - timedelta(minutes=5)).isoformat()

    last_nudge = conn.execute("""
        SELECT id FROM study_room_chat
        WHERE room_id = ? AND user_id = ? AND mensagem LIKE '%[nudge]%' AND created_at > ?
    """, (room["id"], user_id, cinco_min_atras)).fetchone()

    if last_nudge:
        raise HTTPException(status_code=429, detail="Aguarde 5 minutos entre nudges")

    # Enviar mensagem de nudge no chat
    sender_name = _get_user_name(conn, user_id)
    now = datetime.now().isoformat()
    mensagem = f"🔔 [nudge] {sender_name} te mandou um incentivo: De volta ao foco! 💪"

    conn.execute("""
        INSERT INTO study_room_chat (room_id, user_id, nome, mensagem, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (room["id"], user_id, "Sistema", mensagem, now))
    conn.commit()

    log.info(f"Nudge sent from user {user_id} to user {target_user_id} in room {codigo}")
    return {"ok": True, "mensagem": mensagem}


# ============================================================
# 9. COLLABORATIVE QUESTION DISCUSSION
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
    _ensure_discussion_tables(conn)

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo,)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    import json

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
    _ensure_discussion_tables(conn)

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

    nome = _get_user_name(conn, user_id)
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
    _ensure_discussion_tables(conn)

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

    nome = _get_user_name(conn, user_id)
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
    _ensure_discussion_tables(conn)

    import json

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
    _ensure_discussion_tables(conn)

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

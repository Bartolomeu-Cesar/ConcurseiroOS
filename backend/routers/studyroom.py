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

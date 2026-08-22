"""
Router de Study Room — Sala de Estudos Virtual com Timer Compartilhado.
Suporta técnicas Pomodoro e Livre, chat em tempo real via polling.
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_rooms_codigo ON study_rooms(codigo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_participants_room ON study_room_participants(room_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_chat_room ON study_room_chat(room_id)")
    conn.commit()


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


# ============================================================
# ENDPOINTS
# ============================================================


@router.post("/criar")
def criar_sala(
    titulo: str = Body("Sala de Estudos"),
    max_participantes: int = Body(10),
    tecnica: str = Body("pomodoro"),
    duracao_min: int = Body(50),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Cria uma nova sala de estudos."""
    _ensure_studyroom_tables(conn)

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
        INSERT INTO study_rooms (codigo, criador_id, titulo, max_participantes, tecnica, duracao_min, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (codigo, user_id, titulo.strip() or "Sala de Estudos", max_participantes, tecnica, duracao_min, now))
    room_id = cursor.lastrowid

    # Criador entra automaticamente
    conn.execute("""
        INSERT INTO study_room_participants (room_id, user_id, nome, status, ultimo_checkin, joined_at)
        VALUES (?, ?, ?, 'focando', ?, ?)
    """, (room_id, user_id, nome, now, now))
    conn.commit()

    log.info(f"Study room created: {codigo} by user {user_id}")
    return {
        "id": room_id,
        "codigo": codigo,
        "titulo": titulo.strip() or "Sala de Estudos",
        "max_participantes": max_participantes,
        "tecnica": tecnica,
        "duracao_min": duracao_min,
        "criador_id": user_id,
        "created_at": now,
    }


@router.post("/entrar")
def entrar_sala(
    codigo: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Entra em uma sala de estudos existente."""
    _ensure_studyroom_tables(conn)

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
        INSERT INTO study_room_participants (room_id, user_id, nome, status, ultimo_checkin, joined_at)
        VALUES (?, ?, ?, 'focando', ?, ?)
    """, (room["id"], user_id, nome, now, now))
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

    room = conn.execute("SELECT * FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Participantes
    participants = conn.execute(
        "SELECT user_id, nome, status, tempo_estudado_seg, ultimo_checkin, joined_at FROM study_room_participants WHERE room_id = ? ORDER BY joined_at",
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

    # Timer global: tempo desde criação da sala
    created = datetime.fromisoformat(room["created_at"])
    elapsed_sec = int((datetime.now() - created).total_seconds())

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
        "created_at": room["created_at"],
        "participantes": participantes,
        "chat_messages": chat_messages,
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

    conn.execute("""
        UPDATE study_room_participants
        SET status = ?, ultimo_checkin = ?, tempo_estudado_seg = ?
        WHERE room_id = ? AND user_id = ?
    """, (status, now, novo_tempo, room["id"], user_id))
    conn.commit()

    return {"ok": True, "status": status, "tempo_estudado": novo_tempo}


@router.post("/chat/{codigo}")
def enviar_mensagem(
    codigo: str,
    mensagem: str = Body(..., embed=True),
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Envia uma mensagem no chat da sala."""
    _ensure_studyroom_tables(conn)

    if not mensagem or not mensagem.strip():
        raise HTTPException(status_code=400, detail="Mensagem vazia")
    if len(mensagem) > 500:
        raise HTTPException(status_code=400, detail="Mensagem muito longa (máx. 500 caracteres)")

    room = conn.execute("SELECT id FROM study_rooms WHERE codigo = ?", (codigo.upper(),)).fetchone()
    if not room:
        raise HTTPException(status_code=404, detail="Sala não encontrada")

    # Verificar se o usuário é participante
    participant = conn.execute(
        "SELECT id FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room["id"], user_id)
    ).fetchone()
    if not participant:
        raise HTTPException(status_code=403, detail="Você não é participante desta sala")

    nome = _get_user_name(conn, user_id)
    now = datetime.now().isoformat()

    conn.execute("""
        INSERT INTO study_room_chat (room_id, user_id, nome, mensagem, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (room["id"], user_id, nome, mensagem.strip(), now))
    conn.commit()

    return {"ok": True, "mensagem": mensagem.strip(), "created_at": now}


@router.get("/minhas")
def minhas_salas(
    user_id: int = Depends(get_user_id),
    conn=Depends(get_db_session),
):
    """Lista as salas do usuário (que participa ou criou)."""
    _ensure_studyroom_tables(conn)

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

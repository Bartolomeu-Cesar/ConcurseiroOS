"""Funções utilitárias compartilhadas pelo módulo Study Room."""
import random
import string
from datetime import datetime


def generate_code(length=6):
    """Gera um código alfanumérico único para a sala."""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choices(chars, k=length))


def get_user_name(conn, user_id: int) -> str:
    """Busca o nome do usuário pelo ID."""
    row = conn.execute("SELECT nome, username FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        return row["nome"] or row["username"] or f"Estudante #{user_id}"
    return f"Estudante #{user_id}"


def is_focus_cycle(room, elapsed_sec: int) -> bool:
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


def award_focus_xp(conn, user_id: int, tempo_foco_seg: int):
    """Registra sessão de estudo e calcula XP por tempo focado.
    XP: 20 por hora de foco (proporcional).
    Cap: máximo 4h por sessão individual (evita tempo inflado por sessões abandonadas).
    """
    if tempo_foco_seg <= 0:
        return 0

    # Cap: máximo 4 horas por registro individual (14400 seg)
    # Sessões maiores indicam timer abandonado sem stop
    MAX_SESSION_SEC = 4 * 3600
    tempo_foco_seg = min(tempo_foco_seg, MAX_SESSION_SEC)

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
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at) VALUES (?, ?, ?, 'studyroom', ?, ?)",
                ("Study Room", round(horas, 4), hoje, user_id, hoje)
            )
    except Exception:
        try:
            conn.execute(
                "INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'studyroom', ?)",
                ("Study Room", round(horas, 4), hoje, user_id)
            )
        except Exception:
            pass

    # SEMPRE atualizar streak (separado do try acima para garantir execução)
    try:
        conn.execute("""
            INSERT INTO streaks (data, horas_estudadas, user_id) VALUES (?, ?, ?)
            ON CONFLICT(user_id, data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
        """, (hoje, round(horas, 4), user_id, round(horas, 4)))
    except Exception:
        pass

    xp_gained = int(20 * horas)
    return xp_gained


def flush_focus_time(conn, user_id: int, room_id: int):
    """Consolida o tempo de foco pendente de um participante.

    Se o participante está com status 'focando', calcula o tempo decorrido
    desde o último check-in, acumula em `tempo_estudado_seg`, registra em
    `sessoes_estudo`/`streaks` via `award_focus_xp` e reseta `ultimo_checkin`
    para agora (mantendo o participante em foco).

    É idempotente: chamar em sequência sem tempo decorrido não credita nada
    (tempo_extra <= 0 → award_focus_xp retorna 0). Serve tanto para heartbeat
    periódico (não perde tempo se a aba fechar) quanto para a saída da sala.

    Retorna dict com tempo_extra (seg), xp_gained e tempo_estudado total.
    """
    participant = conn.execute(
        "SELECT id, status, ultimo_checkin, tempo_estudado_seg "
        "FROM study_room_participants WHERE room_id = ? AND user_id = ?",
        (room_id, user_id),
    ).fetchone()
    if not participant:
        return {"tempo_extra": 0, "xp_gained": 0, "tempo_estudado": 0}

    now = datetime.now()
    tempo_extra = 0
    if participant["status"] == "focando" and participant["ultimo_checkin"]:
        try:
            last = datetime.fromisoformat(participant["ultimo_checkin"])
            tempo_extra = int((now - last).total_seconds())
        except (ValueError, TypeError):
            tempo_extra = 0

    tempo_extra = max(0, tempo_extra)
    novo_tempo = (participant["tempo_estudado_seg"] or 0) + tempo_extra

    xp_gained = 0
    if tempo_extra > 0:
        xp_gained = award_focus_xp(conn, user_id, tempo_extra)

    # Reseta o check-in para agora, mantendo o status atual. Assim o próximo
    # flush contabiliza apenas o tempo a partir de agora (sem dupla contagem).
    conn.execute(
        "UPDATE study_room_participants SET tempo_estudado_seg = ?, ultimo_checkin = ? "
        "WHERE room_id = ? AND user_id = ?",
        (novo_tempo, now.isoformat(), room_id, user_id),
    )
    conn.commit()

    return {"tempo_extra": tempo_extra, "xp_gained": xp_gained, "tempo_estudado": novo_tempo}

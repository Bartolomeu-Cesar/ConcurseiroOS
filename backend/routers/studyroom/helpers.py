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

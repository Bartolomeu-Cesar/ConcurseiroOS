"""Status de presença social — mostra o que cada usuário está fazendo agora.

Objetivo (prova social): ao ver amigos "Estudando", "Focado" ou "Revisando",
o candidato se sente incentivado a estudar também.

Fluxo:
1. Frontend envia heartbeat periódico (POST /api/social/status) com a atividade atual.
2. Amigos consultam GET /api/social/status/amigos para ver quem está ativo.
3. Status é derivado do tempo: se atualizado há < 5min = online; senão = offline.
"""
from datetime import datetime, timedelta, timezone

from deps import get_user_id
from fastapi import APIRouter, Body, Depends
from pydantic import BaseModel

from database import get_db_session

from .helpers import _get_friend_ids

router = APIRouter(prefix="", tags=["Social"])

# Janela (minutos) para considerar um usuário "online"
ONLINE_THRESHOLD_MIN = 5

# Status válidos que o usuário pode reportar
STATUS_VALIDOS = {
    "estudando": {"label": "Estudando", "emoji": "📖"},
    "focado": {"label": "Em foco (Pomodoro)", "emoji": "🎯"},
    "revisando": {"label": "Revisando (flashcards)", "emoji": "🔁"},
    "questoes": {"label": "Resolvendo questões", "emoji": "✍️"},
    "simulado": {"label": "Fazendo simulado", "emoji": "⏱️"},
    "lendo": {"label": "Lendo PDF", "emoji": "📄"},
    "descansando": {"label": "Descansando", "emoji": "☕"},
    "offline": {"label": "Offline", "emoji": "💤"},
}


class StatusUpdate(BaseModel):
    status: str = "estudando"
    materia: str = ""
    detalhe: str = ""


def _parse_dt(s: str):
    """Parse ISO datetime tolerante."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _is_online(atualizado_em: str) -> bool:
    dt = _parse_dt(atualizado_em)
    if not dt:
        return False
    return (datetime.now(timezone.utc) - dt) <= timedelta(minutes=ONLINE_THRESHOLD_MIN)


@router.post("/api/social/status", summary="Atualizar status de presença (heartbeat)")
def atualizar_status(
    body: StatusUpdate = Body(...),
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Registra/atualiza o status atual do usuário. Serve também como heartbeat."""
    status = body.status if body.status in STATUS_VALIDOS else "estudando"
    materia = (body.materia or "").strip()[:80]
    detalhe = (body.detalhe or "").strip()[:120]
    agora = datetime.now(timezone.utc).isoformat()

    db.execute("""
        INSERT INTO user_status (user_id, status, materia, detalhe, atualizado_em)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            status = excluded.status,
            materia = excluded.materia,
            detalhe = excluded.detalhe,
            atualizado_em = excluded.atualizado_em
    """, (user_id, status, materia, detalhe, agora))
    db.commit()

    return {"ok": True, "status": status, "atualizado_em": agora}


@router.post("/api/social/status/offline", summary="Marcar como offline")
def marcar_offline(db=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Marca o usuário como offline (ex: ao fechar o app)."""
    db.execute(
        "UPDATE user_status SET status = 'offline' WHERE user_id = ?",
        (user_id,)
    )
    db.commit()
    return {"ok": True}


@router.get("/api/social/status/amigos", summary="Status dos amigos (presença)")
def status_amigos(db=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista o status de presença dos amigos, ordenado por online primeiro.

    Retorna quem está online (heartbeat recente) com a atividade atual,
    para servir de prova social/motivação.
    """
    friend_ids = _get_friend_ids(db, user_id)
    if not friend_ids:
        return {"amigos": [], "online_count": 0, "total": 0}

    placeholders = ",".join("?" * len(friend_ids))
    rows = db.execute(f"""
        SELECT u.id, u.nome, u.username, u.avatar,
               s.status, s.materia, s.detalhe, s.atualizado_em
        FROM users u
        LEFT JOIN user_status s ON s.user_id = u.id
        WHERE u.id IN ({placeholders})
    """, tuple(friend_ids)).fetchall()

    amigos = []
    online_count = 0
    for r in rows:
        status_raw = r["status"] or "offline"
        online = _is_online(r["atualizado_em"]) and status_raw != "offline"
        if online:
            online_count += 1
        else:
            status_raw = "offline"

        info = STATUS_VALIDOS.get(status_raw, STATUS_VALIDOS["offline"])
        amigos.append({
            "user_id": r["id"],
            "nome": r["nome"] or r["username"] or f"Concurseiro #{r['id']}",
            "avatar": r["avatar"] or "👤",
            "online": online,
            "status": status_raw,
            "status_label": info["label"],
            "status_emoji": info["emoji"],
            "materia": r["materia"] or "" if online else "",
            "detalhe": r["detalhe"] or "" if online else "",
            "atualizado_em": r["atualizado_em"] or "",
        })

    # Ordenar: online primeiro, depois por nome
    amigos.sort(key=lambda a: (not a["online"], a["nome"].lower()))

    return {"amigos": amigos, "online_count": online_count, "total": len(amigos)}


@router.get("/api/social/status/resumo", summary="Resumo de atividade para incentivo")
def resumo_atividade(db=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna uma mensagem motivacional baseada em quantos amigos estão estudando agora."""
    data = status_amigos(db, user_id)
    online = data["online_count"]
    estudando = sum(1 for a in data["amigos"] if a["online"] and a["status"] in ("estudando", "focado", "revisando", "questoes", "simulado", "lendo"))

    if estudando >= 3:
        msg = f"🔥 {estudando} amigos estão estudando agora! Junte-se a eles."
    elif estudando == 2:
        msg = "💪 2 amigos estão focados nos estudos. Bora também!"
    elif estudando == 1:
        msg = "👀 1 amigo está estudando agora. Que tal acompanhar?"
    else:
        msg = "🚀 Seja o primeiro a estudar hoje e inspire seus amigos!"

    return {"mensagem": msg, "online_count": online, "estudando_count": estudando}

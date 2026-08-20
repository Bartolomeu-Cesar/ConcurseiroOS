"""Router de Desafios Semanais."""
from datetime import datetime

from fastapi import APIRouter, Depends

from database import get_db_session
from deps import get_user_id
from logger import log
from models import DesafioCreate

router = APIRouter(prefix="", tags=["Desafios"])


@router.get("/api/desafios")
def list_desafios(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM desafios WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/desafios")
def create_desafio(body: DesafioCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO desafios (titulo, meta_tipo, meta_valor, materia, dias, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.titulo, body.meta_tipo, body.meta_valor, body.materia, body.dias, datetime.now().isoformat(), user_id)
    )
    conn.commit()
    log.info(f"Desafio created: {body.titulo}")
    return {"id": cur.lastrowid, "ok": True}


@router.put("/api/desafios/{id}/progresso")
def update_desafio_progresso(id: int, valor: int = 1, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("UPDATE desafios SET progresso = progresso + ? WHERE id = ? AND user_id = ?", (valor, id, user_id))
    # Verificar se completou
    desafio = conn.execute("SELECT * FROM desafios WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if desafio and desafio["progresso"] >= desafio["meta_valor"]:
        conn.execute("UPDATE desafios SET finalizado = 1 WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True, "progresso": desafio["progresso"] if desafio else 0}


@router.delete("/api/desafios/{id}")
def delete_desafio(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM desafios WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}

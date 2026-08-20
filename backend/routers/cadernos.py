"""Router de Cadernos de Estudo."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from logger import log
from models import CadernoAddItem, CadernoCreate

router = APIRouter(prefix="", tags=["Cadernos"])


@router.get("/api/cadernos")
def list_cadernos(conn=Depends(get_db_session)):
    cadernos = conn.execute("SELECT * FROM cadernos ORDER BY created_at DESC").fetchall()
    result = []
    for c in cadernos:
        count = conn.execute("SELECT COUNT(*) FROM caderno_itens WHERE caderno_id = ?", (c[0],)).fetchone()[0]
        d = dict(c)
        d["total_itens"] = count
        result.append(d)
    return result


@router.post("/api/cadernos")
def create_caderno(body: CadernoCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO cadernos (nome, descricao, created_at) VALUES (?, ?, ?)",
                       (body.nome, body.descricao, datetime.now().isoformat()))
    conn.commit()
    log.info(f"Caderno created: {body.nome}")
    return {"id": cur.lastrowid, "ok": True}


@router.post("/api/cadernos/{id}/adicionar")
def add_to_caderno(id: int, body: CadernoAddItem, conn=Depends(get_db_session)):
    conn.execute("INSERT INTO caderno_itens (caderno_id, tipo, item_id) VALUES (?, ?, ?)",
                 (id, body.tipo, body.item_id))
    conn.commit()
    return {"ok": True}


@router.get("/api/cadernos/{id}")
def get_caderno(id: int, conn=Depends(get_db_session)):
    caderno = conn.execute("SELECT * FROM cadernos WHERE id = ?", (id,)).fetchone()
    if not caderno:
        raise HTTPException(status_code=404, detail="Caderno não encontrado")
    itens = conn.execute("SELECT * FROM caderno_itens WHERE caderno_id = ?", (id,)).fetchall()
    return {"caderno": dict(caderno), "itens": [dict(i) for i in itens]}


@router.delete("/api/cadernos/{id}")
def delete_caderno(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM caderno_itens WHERE caderno_id = ?", (id,))
    conn.execute("DELETE FROM cadernos WHERE id = ?", (id,))
    conn.commit()
    log.info(f"Caderno deleted: {id}")
    return {"ok": True}

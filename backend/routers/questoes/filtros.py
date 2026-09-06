"""Filtros de questões salvos (inspirado no QConcursos).

Permite ao usuário salvar um conjunto de filtros (matéria, tópico, banca,
dificuldade, tipo, etc.) sob um nome e reaplicá-lo depois — evita reconfigurar
os mesmos filtros toda vez. Multi-tenant: tudo filtrado por user_id.
"""

import json

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException
from sanitize import sanitize_input

from database import get_db_session
from logger import log
from utils import today_str

router = APIRouter()


@router.get(
    "/api/questoes/filtros-salvos",
    summary="Listar filtros salvos",
    description="Retorna os filtros de questões salvos pelo usuário (nome + objeto de filtros).",
)
def listar_filtros_salvos(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute(
        "SELECT id, nome, filtros_json, created_at FROM filtros_salvos WHERE user_id = ? ORDER BY nome", (user_id,)
    ).fetchall()
    out = []
    for r in rows:
        try:
            filtros = json.loads(r["filtros_json"] or "{}")
        except Exception:
            filtros = {}
        out.append({"id": r["id"], "nome": r["nome"], "filtros": filtros, "created_at": r["created_at"]})
    return out


@router.post(
    "/api/questoes/filtros-salvos",
    summary="Salvar filtro",
    description="Salva (ou atualiza, se o nome já existir) um conjunto de filtros sob um nome.",
)
def salvar_filtro(
    body: dict = Body(...),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    nome = sanitize_input(str(body.get("nome", "")), max_length=100).strip()
    if not nome:
        raise HTTPException(status_code=400, detail="Informe um nome para o filtro.")

    filtros = body.get("filtros", {})
    if not isinstance(filtros, dict):
        raise HTTPException(status_code=400, detail="Filtros inválidos.")
    filtros_json = json.dumps(filtros, ensure_ascii=False)

    # Upsert por (user_id, nome) — respeita o índice único.
    existing = conn.execute("SELECT id FROM filtros_salvos WHERE user_id = ? AND nome = ?", (user_id, nome)).fetchone()
    if existing:
        conn.execute(
            "UPDATE filtros_salvos SET filtros_json = ? WHERE id = ? AND user_id = ?",
            (filtros_json, existing["id"], user_id),
        )
        conn.commit()
        return {"id": existing["id"], "ok": True, "atualizado": True}

    cur = conn.execute(
        "INSERT INTO filtros_salvos (user_id, nome, filtros_json, created_at) VALUES (?, ?, ?, ?)",
        (user_id, nome, filtros_json, today_str()),
    )
    conn.commit()
    log.info(f"Filtro salvo: user={user_id} nome={nome}")
    return {"id": cur.lastrowid, "ok": True, "atualizado": False}


@router.delete(
    "/api/questoes/filtros-salvos/{filtro_id}",
    summary="Excluir filtro salvo",
    description="Remove um filtro salvo do usuário.",
)
def excluir_filtro(filtro_id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("DELETE FROM filtros_salvos WHERE id = ? AND user_id = ?", (filtro_id, user_id))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Filtro não encontrado.")
    return {"ok": True}

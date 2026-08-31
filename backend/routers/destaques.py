"""Router da camada de destaques (marca-texto) persistentes por página do PDF.

Cada destaque guarda o trecho selecionado (texto), a cor e os retângulos da
seleção em coordenadas relativas 0-1 à página (uma seleção pode gerar vários
retângulos — ex: várias linhas). É por PDF + página + usuário.
"""
import json
from datetime import datetime

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException
from sanitize import sanitize_input
from schemas import DestaqueCreate, DestaqueUpdate, OkResponse

from database import get_db_session
from logger import log

router = APIRouter(prefix="", tags=["Destaques"])

# Paleta de cores permitidas (chaves; o frontend mapeia para o valor CSS).
_CORES_VALIDAS = {"yellow", "green", "blue", "pink", "orange"}
_ESTILOS_VALIDOS = {"highlight", "underline", "strike", "box"}
_MAX_RECTS = 60


def _destaque_to_dict(row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "pdf_path": row["pdf_path"],
        "pagina": row["pagina"],
        "cor": row["cor"],
        "texto": row["texto"],
        "rects": row["rects"] or "[]",
        "estilo": (row["estilo"] or "highlight") if "estilo" in keys else "highlight",
        "comentario": (row["comentario"] or "") if "comentario" in keys else "",
        "created_at": row["created_at"],
    }


def _validar_rects(raw: str) -> str:
    """Valida/normaliza o JSON de retângulos (lista de {x,y,w,h} em 0-1).

    Retorna JSON compacto. Rejeita se não houver nenhum retângulo válido.
    """
    raw = (raw or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail="rects é obrigatório.")
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="rects deve ser JSON válido.")
    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail="rects deve ser uma lista de retângulos.")
    if len(data) > _MAX_RECTS:
        raise HTTPException(status_code=422, detail=f"Máximo de {_MAX_RECTS} retângulos por destaque.")
    limpo = []
    for r in data:
        if not isinstance(r, dict):
            continue
        try:
            x, y, w, h = float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"])
        except (KeyError, TypeError, ValueError):
            continue
        x = max(0.0, min(1.0, x)); y = max(0.0, min(1.0, y))
        w = max(0.0, min(1.0, w)); h = max(0.0, min(1.0, h))
        if w <= 0 or h <= 0:
            continue
        limpo.append({"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)})
    if not limpo:
        raise HTTPException(status_code=422, detail="Nenhum retângulo válido em rects.")
    return json.dumps(limpo, separators=(",", ":"))


@router.get("/api/destaques/{pdf_path:path}", summary="Listar destaques de um PDF")
def get_destaques(pdf_path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if ".." in pdf_path:
        raise HTTPException(status_code=400, detail="Caminho inválido")
    rows = conn.execute(
        "SELECT * FROM destaques_pdf WHERE pdf_path = ? AND user_id = ? ORDER BY pagina, id",
        (pdf_path, user_id),
    ).fetchall()
    return [_destaque_to_dict(r) for r in rows]


@router.post("/api/destaques", summary="Criar destaque (marca-texto)")
def create_destaque(body: DestaqueCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if ".." in body.pdf_path or not body.pdf_path.strip():
        raise HTTPException(status_code=400, detail="Caminho de PDF inválido")
    cor = (body.cor or "yellow").strip().lower()
    if cor not in _CORES_VALIDAS:
        raise HTTPException(status_code=422, detail=f"Cor inválida. Use: {', '.join(sorted(_CORES_VALIDAS))}.")
    estilo = (body.estilo or "highlight").strip().lower()
    if estilo not in _ESTILOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"Estilo inválido. Use: {', '.join(sorted(_ESTILOS_VALIDOS))}.")
    pagina = max(1, int(body.pagina or 1))
    texto = sanitize_input(body.texto or "", max_length=5000)
    comentario = sanitize_input(body.comentario or "", max_length=5000)
    rects = _validar_rects(body.rects)

    cur = conn.execute(
        """INSERT INTO destaques_pdf (user_id, pdf_path, pagina, cor, texto, rects, estilo, comentario, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, body.pdf_path, pagina, cor, texto, rects, estilo, comentario, datetime.now().isoformat()),
    )
    conn.commit()
    log.info(f"Destaque criado: {body.pdf_path} p.{pagina} cor={cor} estilo={estilo} user={user_id}")
    return {"ok": True, "id": cur.lastrowid, "pagina": pagina, "cor": cor, "estilo": estilo}


@router.put("/api/destaques/{id}", response_model=OkResponse, summary="Editar destaque (cor/estilo/comentário)")
def update_destaque(id: int, body: DestaqueUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    existing = conn.execute("SELECT id FROM destaques_pdf WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Destaque não encontrado")
    campos, valores = [], []
    if body.cor is not None:
        cor = body.cor.strip().lower()
        if cor not in _CORES_VALIDAS:
            raise HTTPException(status_code=422, detail="Cor inválida.")
        campos.append("cor = ?"); valores.append(cor)
    if body.estilo is not None:
        estilo = body.estilo.strip().lower()
        if estilo not in _ESTILOS_VALIDOS:
            raise HTTPException(status_code=422, detail="Estilo inválido.")
        campos.append("estilo = ?"); valores.append(estilo)
    if body.comentario is not None:
        campos.append("comentario = ?"); valores.append(sanitize_input(body.comentario, max_length=5000))
    if campos:
        valores.extend([id, user_id])
        conn.execute(f"UPDATE destaques_pdf SET {', '.join(campos)} WHERE id = ? AND user_id = ?", valores)
        conn.commit()
    return {"ok": True}


@router.delete("/api/destaques/{id}", response_model=OkResponse, summary="Excluir destaque")
def delete_destaque(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM destaques_pdf WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}

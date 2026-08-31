"""Router do Caderno de Revisão por PDF.

Permite montar um "caderno de revisão" a partir de blocos capturados do PDF
original: recortes de imagem da página, resumos gerados por IA, trechos de
texto e notas. O caderno é por PDF e por usuário.

Técnicas de estudo aplicadas: Distributed Summary, Dual Coding (imagem+texto)
e Cognitive Load Segmenting (blocos curtos e independentes).
"""
from datetime import datetime

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sanitize import sanitize_input
from schemas import OkResponse, RevisaoBlocoCreate, RevisaoBlocoUpdate

from database import get_db_session
from logger import log

router = APIRouter(prefix="", tags=["Revisão"])

_TIPOS_VALIDOS = {"recorte", "resumo_ia", "texto", "nota"}


def _bloco_to_dict(row) -> dict:
    return {
        "id": row["id"],
        "pdf_path": row["pdf_path"],
        "tipo": row["tipo"],
        "titulo": row["titulo"],
        "conteudo": row["conteudo"],
        "imagem_data": row["imagem_data"],
        "pagina": row["pagina"],
        "ordem": row["ordem"],
        "created_at": row["created_at"],
    }


@router.get("/api/revisao/{pdf_path:path}/export", summary="Exportar caderno de revisão (Markdown)")
def export_revisao(pdf_path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Exporta o caderno de revisão de um PDF como Markdown.

    Imagens de recorte são embutidas como data URI (![...](data:image/...)).
    """
    if ".." in pdf_path:
        raise HTTPException(status_code=400, detail="Caminho inválido")

    rows = conn.execute(
        "SELECT * FROM revisao_blocos WHERE pdf_path = ? AND user_id = ? ORDER BY ordem, id",
        (pdf_path, user_id),
    ).fetchall()

    nome = pdf_path.split("/")[-1].replace(".pdf", "").replace("_", " ")
    linhas = [f"# Caderno de Revisão — {nome}", ""]

    for bloco in rows:
        b = _bloco_to_dict(bloco)
        titulo = (b["titulo"] or "").strip()
        if titulo:
            linhas.append(f"## {titulo}")
            linhas.append("")
        linhas.append(f"_Página {b['pagina']}_")
        linhas.append("")
        if b["tipo"] == "recorte" and b["imagem_data"]:
            linhas.append(f"![Recorte p.{b['pagina']}]({b['imagem_data']})")
            linhas.append("")
        if (b["conteudo"] or "").strip():
            linhas.append(b["conteudo"].strip())
            linhas.append("")
        linhas.append("---")
        linhas.append("")

    md = "\n".join(linhas)
    filename = f"revisao_{nome.replace(' ', '_')}.md"
    return PlainTextResponse(
        md,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/revisao/{pdf_path:path}", summary="Listar blocos de revisão de um PDF")
def get_revisao(pdf_path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if ".." in pdf_path:
        raise HTTPException(status_code=400, detail="Caminho inválido")
    rows = conn.execute(
        "SELECT * FROM revisao_blocos WHERE pdf_path = ? AND user_id = ? ORDER BY ordem, id",
        (pdf_path, user_id),
    ).fetchall()
    return [_bloco_to_dict(r) for r in rows]


@router.post("/api/revisao", summary="Criar bloco de revisão")
def create_revisao(body: RevisaoBlocoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    tipo = (body.tipo or "recorte").strip().lower()
    if tipo not in _TIPOS_VALIDOS:
        raise HTTPException(status_code=422, detail=f"Tipo inválido. Use: {', '.join(sorted(_TIPOS_VALIDOS))}.")
    if ".." in body.pdf_path or not body.pdf_path.strip():
        raise HTTPException(status_code=400, detail="Caminho de PDF inválido")

    # Um recorte precisa de imagem; os demais tipos precisam de conteúdo.
    imagem = (body.imagem_data or "").strip()
    conteudo = sanitize_input(body.conteudo or "", max_length=20000)
    titulo = sanitize_input(body.titulo or "", max_length=300)

    if tipo == "recorte" and not imagem:
        raise HTTPException(status_code=422, detail="Recorte requer imagem_data.")
    if tipo != "recorte" and not conteudo:
        raise HTTPException(status_code=422, detail="Bloco de texto requer conteúdo.")

    # Aceitar apenas data URI de imagem para o recorte (evita payload arbitrário).
    if imagem and not imagem.startswith("data:image/"):
        raise HTTPException(status_code=422, detail="imagem_data deve ser um data URI de imagem.")

    # Próxima ordem = fim da lista
    prox = conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) + 1 FROM revisao_blocos WHERE pdf_path = ? AND user_id = ?",
        (body.pdf_path, user_id),
    ).fetchone()[0]

    cur = conn.execute(
        """INSERT INTO revisao_blocos
           (user_id, pdf_path, tipo, titulo, conteudo, imagem_data, pagina, ordem, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, body.pdf_path, tipo, titulo, conteudo, imagem, body.pagina, prox, datetime.now().isoformat()),
    )
    conn.commit()
    log.info(f"Revisão bloco criado: {body.pdf_path} p.{body.pagina} tipo={tipo} user={user_id}")
    return {"ok": True, "id": cur.lastrowid, "ordem": prox}


@router.post("/api/revisao/{id}/flashcard", summary="Transformar bloco de revisão em flashcard (FSRS)")
def bloco_para_flashcard(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Cria um flashcard a partir de um bloco de revisão.

    Fecha o ciclo de revisão espaçada: o material capturado do PDF vira um item
    revisável pelo FSRS. Para blocos de texto/resumo, título vira a pergunta e o
    conteúdo a resposta. Para recortes (imagem), gera uma pergunta de recall com
    referência à página.
    """
    from utils import today_str

    bloco = conn.execute(
        "SELECT * FROM revisao_blocos WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not bloco:
        raise HTTPException(status_code=404, detail="Bloco não encontrado")

    b = _bloco_to_dict(bloco)
    titulo = (b["titulo"] or "").strip()
    conteudo = (b["conteudo"] or "").strip()
    pagina = b["pagina"]
    materia = sanitize_input((b["pdf_path"].split("/")[0] if "/" in b["pdf_path"] else ""), max_length=200)

    if b["tipo"] == "recorte":
        # Recall ativo sobre o recorte visual.
        pergunta = titulo or f"O que você lembra do recorte da página {pagina}?"
        resposta = conteudo or f"(Recorte da página {pagina} — confira no caderno de revisão do PDF.)"
    else:
        # Texto/resumo/nota: título (ou 1ª linha) vira pergunta; conteúdo vira resposta.
        if titulo and conteudo:
            pergunta, resposta = titulo, conteudo
        elif conteudo:
            linhas = conteudo.split("\n", 1)
            pergunta = linhas[0][:200]
            resposta = linhas[1].strip() if len(linhas) > 1 else conteudo
        else:
            raise HTTPException(status_code=422, detail="Bloco sem conteúdo para gerar flashcard.")

    pergunta = sanitize_input(pergunta, max_length=2000)
    resposta = sanitize_input(resposta, max_length=5000)

    try:
        from plans import enforce_plan_limit
        enforce_plan_limit(conn, user_id, "flashcards")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - limite de plano é best-effort aqui
        pass

    cur = conn.execute(
        "INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id) VALUES (?, ?, ?, ?, ?)",
        (pergunta, resposta, today_str(), materia, user_id),
    )
    conn.commit()
    log.info(f"Flashcard criado a partir de bloco de revisão {id} (user={user_id})")
    return {"ok": True, "flashcard_id": cur.lastrowid, "pergunta": pergunta, "materia": materia}


@router.put("/api/revisao/{id}", response_model=OkResponse, summary="Editar/reordenar bloco de revisão")
def update_revisao(id: int, body: RevisaoBlocoUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    existing = conn.execute(
        "SELECT id FROM revisao_blocos WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Bloco não encontrado")

    campos = []
    valores = []
    if body.titulo is not None:
        campos.append("titulo = ?")
        valores.append(sanitize_input(body.titulo, max_length=300))
    if body.conteudo is not None:
        campos.append("conteudo = ?")
        valores.append(sanitize_input(body.conteudo, max_length=20000))
    if body.ordem is not None:
        campos.append("ordem = ?")
        valores.append(body.ordem)

    if campos:
        valores.extend([id, user_id])
        conn.execute(
            f"UPDATE revisao_blocos SET {', '.join(campos)} WHERE id = ? AND user_id = ?",
            valores,
        )
        conn.commit()
    return {"ok": True}


@router.delete("/api/revisao/{id}", response_model=OkResponse, summary="Excluir bloco de revisão")
def delete_revisao(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM revisao_blocos WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}

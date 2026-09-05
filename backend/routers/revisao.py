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
_TAGS_VALIDAS = {"", "decorar", "entender", "pegadinha", "revisar"}


def _validar_tag(raw) -> str:
    tag = (raw or "").strip().lower()
    if tag not in _TAGS_VALIDAS:
        raise HTTPException(status_code=422, detail=f"Tag inválida. Use: {', '.join(sorted(t for t in _TAGS_VALIDAS if t))}.")
    return tag


def _bloco_to_dict(row) -> dict:
    # oclusoes/tag podem não existir em bancos muito antigos (defensivo).
    keys = row.keys()
    return {
        "id": row["id"],
        "pdf_path": row["pdf_path"],
        "tipo": row["tipo"],
        "titulo": row["titulo"],
        "conteudo": row["conteudo"],
        "imagem_data": row["imagem_data"],
        "pagina": row["pagina"],
        "ordem": row["ordem"],
        "oclusoes": (row["oclusoes"] or "") if "oclusoes" in keys else "",
        "tag": (row["tag"] or "") if "tag" in keys else "",
        "created_at": row["created_at"],
    }


def _validar_oclusoes(raw: str) -> str:
    """Valida e normaliza o JSON de oclusões (lista de retângulos 0-1).

    Retorna JSON compacto válido ou '' se vazio/inválido. Limita a 60 regiões.
    """
    import json

    raw = (raw or "").strip()
    if not raw:
        return ""
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="oclusoes deve ser JSON válido.") from None
    if not isinstance(data, list):
        raise HTTPException(status_code=422, detail="oclusoes deve ser uma lista de retângulos.")
    if len(data) > 60:
        raise HTTPException(status_code=422, detail="Máximo de 60 regiões de oclusão.")
    limpo = []
    for r in data:
        if not isinstance(r, dict):
            continue
        try:
            x, y, w, h = float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"])
        except (KeyError, TypeError, ValueError):
            continue
        # Clampa em [0,1] para evitar valores absurdos.
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        w = max(0.0, min(1.0, w))
        h = max(0.0, min(1.0, h))
        if w <= 0 or h <= 0:
            continue
        limpo.append({"x": round(x, 4), "y": round(y, 4), "w": round(w, 4), "h": round(h, 4)})
    return json.dumps(limpo, separators=(",", ":")) if limpo else ""


# ============================================================
# AGENDAMENTO ESPAÇADO DO CADERNO (Spaced Practice por PDF)
# ============================================================
# Escada de intervalos (dias) que expande a cada revisão concluída.
_ESCADA_INTERVALOS = [1, 3, 7, 15, 30, 60]


def _proximo_intervalo(atual: int) -> int:
    """Retorna o próximo intervalo da escada a partir do atual."""
    for iv in _ESCADA_INTERVALOS:
        if iv > atual:
            return iv
    return _ESCADA_INTERVALOS[-1]


def _agenda_to_dict(row) -> dict:
    return {
        "pdf_path": row["pdf_path"],
        "proxima_revisao": row["proxima_revisao"],
        "intervalo_dias": row["intervalo_dias"],
        "revisoes_count": row["revisoes_count"],
        "ultima_revisao": row["ultima_revisao"] if "ultima_revisao" in row.keys() else "",
    }


@router.get("/api/revisao-agenda/hoje", summary="Cadernos de revisão para revisar hoje")
def agenda_hoje(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista cadernos cujo agendamento venceu (proxima_revisao <= hoje).

    Usado pelo dashboard para lembrar o aluno de revisar (Spaced Practice)."""
    from utils import today_str

    hoje = today_str()
    rows = conn.execute(
        """SELECT a.*, (SELECT COUNT(*) FROM revisao_blocos b
                        WHERE b.pdf_path = a.pdf_path AND b.user_id = a.user_id) AS blocos
           FROM revisao_agenda a
           WHERE a.user_id = ? AND a.proxima_revisao <= ?
           ORDER BY a.proxima_revisao""",
        (user_id, hoje),
    ).fetchall()
    itens = []
    for r in rows:
        d = _agenda_to_dict(r)
        d["blocos"] = r["blocos"]
        d["nome"] = r["pdf_path"].split("/")[-1].replace(".pdf", "").replace("_", " ")
        itens.append(d)
    return {"hoje": hoje, "total": len(itens), "cadernos": itens}


@router.get("/api/revisao-agenda/{pdf_path:path}", summary="Ler agendamento do caderno de um PDF")
def get_agenda(pdf_path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if ".." in pdf_path:
        raise HTTPException(status_code=400, detail="Caminho inválido")
    row = conn.execute(
        "SELECT * FROM revisao_agenda WHERE pdf_path = ? AND user_id = ?", (pdf_path, user_id)
    ).fetchone()
    if not row:
        return {"agendado": False}
    d = _agenda_to_dict(row)
    d["agendado"] = True
    return d


@router.post("/api/revisao-agenda", summary="Agendar/reprogramar revisão do caderno")
def set_agenda(body: dict, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Agenda a próxima revisão do caderno. Body: {pdf_path, dias?}.

    Se `dias` for informado (>0), usa esse intervalo; senão inicia em 1 dia.
    Idempotente por (user_id, pdf_path) — regrava se já existir."""
    from datetime import date, timedelta

    pdf_path = (body.get("pdf_path") or "").strip()
    if not pdf_path or ".." in pdf_path:
        raise HTTPException(status_code=400, detail="pdf_path inválido")
    try:
        dias = int(body.get("dias") or 0)
    except (TypeError, ValueError):
        dias = 0
    if dias <= 0:
        dias = _ESCADA_INTERVALOS[0]
    dias = max(1, min(365, dias))

    proxima = (date.today() + timedelta(days=dias)).isoformat()
    agora = datetime.now().isoformat()
    existing = conn.execute(
        "SELECT id FROM revisao_agenda WHERE pdf_path = ? AND user_id = ?", (pdf_path, user_id)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE revisao_agenda SET proxima_revisao = ?, intervalo_dias = ?, updated_at = ? WHERE id = ?",
            (proxima, dias, agora, existing[0]),
        )
    else:
        conn.execute(
            """INSERT INTO revisao_agenda (user_id, pdf_path, proxima_revisao, intervalo_dias, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, pdf_path, proxima, dias, agora, agora),
        )
    conn.commit()
    return {"ok": True, "proxima_revisao": proxima, "intervalo_dias": dias}


@router.post("/api/revisao-agenda/{pdf_path:path}/revisado", summary="Marcar caderno como revisado (expande intervalo)")
def marcar_revisado(pdf_path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Registra que o caderno foi revisado: expande o intervalo (escada) e
    agenda a próxima revisão. Cria a agenda se ainda não existir."""
    from datetime import date, timedelta

    if ".." in pdf_path:
        raise HTTPException(status_code=400, detail="Caminho inválido")
    agora = datetime.now().isoformat()
    hoje = date.today()
    row = conn.execute(
        "SELECT * FROM revisao_agenda WHERE pdf_path = ? AND user_id = ?", (pdf_path, user_id)
    ).fetchone()
    if row:
        novo_intervalo = _proximo_intervalo(row["intervalo_dias"])
        count = row["revisoes_count"] + 1
        proxima = (hoje + timedelta(days=novo_intervalo)).isoformat()
        conn.execute(
            """UPDATE revisao_agenda SET proxima_revisao = ?, intervalo_dias = ?,
               revisoes_count = ?, ultima_revisao = ?, updated_at = ? WHERE id = ?""",
            (proxima, novo_intervalo, count, hoje.isoformat(), agora, row["id"]),
        )
    else:
        novo_intervalo = _proximo_intervalo(_ESCADA_INTERVALOS[0])
        count = 1
        proxima = (hoje + timedelta(days=novo_intervalo)).isoformat()
        conn.execute(
            """INSERT INTO revisao_agenda (user_id, pdf_path, proxima_revisao, intervalo_dias,
               revisoes_count, ultima_revisao, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, pdf_path, proxima, novo_intervalo, count, hoje.isoformat(), agora, agora),
        )
    conn.commit()
    return {"ok": True, "proxima_revisao": proxima, "intervalo_dias": novo_intervalo, "revisoes_count": count}


@router.delete("/api/revisao-agenda/{pdf_path:path}", response_model=OkResponse, summary="Cancelar agendamento do caderno")
def delete_agenda(pdf_path: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if ".." in pdf_path:
        raise HTTPException(status_code=400, detail="Caminho inválido")
    conn.execute("DELETE FROM revisao_agenda WHERE pdf_path = ? AND user_id = ?", (pdf_path, user_id))
    conn.commit()
    return {"ok": True}


# ============================================================
# AUTO-GERAR BLOCOS DE REVISÃO COM IA
# ============================================================

_SYSTEM_PROMPT_REVISAO_IA = (
    "Você é um professor que monta cadernos de revisão para concursos. A partir do "
    "TRECHO de material fornecido, gere blocos de revisão CONCISOS e independentes, "
    "cada um cobrindo UM ponto importante. Responda APENAS em JSON, no formato: "
    '[{"titulo": "Título curto do ponto", "conteudo": "Resumo objetivo em 1-4 frases, '
    'com o essencial para revisar rápido."}]. '
    "Regras: foque no que mais cai em prova; use linguagem clara; NÃO invente conteúdo "
    "fora do trecho; produza entre 3 e 10 blocos."
)


@router.post("/api/revisao-ia/gerar", summary="Auto-gerar blocos de revisão com IA a partir do PDF")
def gerar_revisao_ia(body: dict, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lê um intervalo de páginas do PDF e gera blocos de resumo (tipo resumo_ia)
    salvos direto no caderno de revisão. Reusa a infra de IA do ai_tutor.

    Body: {pdf_path, pagina_inicial, pagina_final?, materia?}."""
    pdf_path = (body.get("pdf_path") or "").strip()
    if not pdf_path or ".." in pdf_path:
        raise HTTPException(status_code=400, detail="pdf_path inválido")
    try:
        pg_ini = max(1, int(body.get("pagina_inicial") or 1))
    except (TypeError, ValueError):
        pg_ini = 1
    try:
        pg_fim = int(body.get("pagina_final")) if body.get("pagina_final") else None
    except (TypeError, ValueError):
        pg_fim = None
    if pg_fim is not None and pg_fim < pg_ini:
        raise HTTPException(status_code=422, detail="Página final deve ser >= inicial.")

    # Reusa helpers do ai_tutor (import tardio: evita ciclo e mantém patch de testes).
    from routers import ai_tutor
    from routers.questoes.importacao import _extrair_texto_pdf_intervalo

    budget = ai_tutor._check_budget(conn, user_id)

    caminho = ai_tutor._resolver_pdf_path(pdf_path)
    try:
        texto, _total = _extrair_texto_pdf_intervalo(caminho, pg_ini, pg_fim)
    except Exception:
        raise HTTPException(status_code=400, detail="Não foi possível extrair texto do PDF.") from None

    texto = (texto or "").strip()
    if len(texto) < 50:
        raise HTTPException(status_code=400, detail="Trecho sem texto suficiente (PDF escaneado ou intervalo vazio).")

    trecho = texto[: ai_tutor._MAX_CHARS_TRECHO_PDF]
    nome_pdf = pdf_path.split("/")[-1].replace(".pdf", "")
    materia = (body.get("materia") or nome_pdf).strip()
    contexto = f"páginas {pg_ini}" + (f"–{pg_fim}" if pg_fim else " em diante")

    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT_REVISAO_IA},
        {"role": "user", "content": f"Material: {nome_pdf} ({contexto}). Matéria: {materia}.\n\nTRECHO:\n{trecho}"},
    ]
    text, tokens = ai_tutor.call_llm_sync(messages, max_tokens=2000)
    ai_tutor._record_usage(conn, user_id, tokens, "revisao_ia", f"{nome_pdf} {contexto}", text[:500])

    blocos_ia = ai_tutor._parse_json_llm(text)
    if not isinstance(blocos_ia, list) or not blocos_ia:
        raise HTTPException(status_code=422, detail="A IA não retornou blocos. Tente outro intervalo de páginas.")

    # Próxima ordem
    prox = conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) + 1 FROM revisao_blocos WHERE pdf_path = ? AND user_id = ?",
        (pdf_path, user_id),
    ).fetchone()[0]

    salvos = 0
    agora = datetime.now().isoformat()
    for b in blocos_ia:
        if not isinstance(b, dict):
            continue
        titulo = sanitize_input((b.get("titulo") or "").strip(), max_length=300)
        conteudo = sanitize_input((b.get("conteudo") or "").strip(), max_length=20000)
        if not conteudo:
            continue
        conn.execute(
            """INSERT INTO revisao_blocos
               (user_id, pdf_path, tipo, titulo, conteudo, imagem_data, pagina, ordem, oclusoes, tag, created_at)
               VALUES (?, ?, 'resumo_ia', ?, ?, '', ?, ?, '', '', ?)""",
            (user_id, pdf_path, titulo, conteudo, pg_ini, prox + salvos, agora),
        )
        salvos += 1
    if salvos:
        conn.commit()
    log.info(f"[Revisão IA] {salvos} blocos gerados p/ {pdf_path} user={user_id}")

    return {
        "ok": True,
        "salvos": salvos,
        "tecnica": "Distributed Summary + Cognitive Load Segmenting",
        "tokens_usados": tokens,
        "budget": budget,
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

    oclusoes = _validar_oclusoes(getattr(body, "oclusoes", "") or "")
    tag = _validar_tag(getattr(body, "tag", "") or "")

    # Próxima ordem = fim da lista
    prox = conn.execute(
        "SELECT COALESCE(MAX(ordem), -1) + 1 FROM revisao_blocos WHERE pdf_path = ? AND user_id = ?",
        (body.pdf_path, user_id),
    ).fetchone()[0]

    cur = conn.execute(
        """INSERT INTO revisao_blocos
           (user_id, pdf_path, tipo, titulo, conteudo, imagem_data, pagina, ordem, oclusoes, tag, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (user_id, body.pdf_path, tipo, titulo, conteudo, imagem, body.pagina, prox, oclusoes, tag, datetime.now().isoformat()),
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
    if body.oclusoes is not None:
        campos.append("oclusoes = ?")
        valores.append(_validar_oclusoes(body.oclusoes))
    if body.tag is not None:
        campos.append("tag = ?")
        valores.append(_validar_tag(body.tag))

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

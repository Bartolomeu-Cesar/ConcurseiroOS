import os
import re
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from pypdf import PdfReader

from constants import SM2_FIRST_INTERVAL, SM2_INITIAL_EF, SM2_MIN_EF, SM2_SECOND_INTERVAL
from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import EditalCreate, EditalHoras, EditalPdfLink, EditalReviewSM2, NotaTopicoCreate, OkResponse, ResumoCreate
from sanitize import sanitize_input
from schemas import CreateEditalInfoRequest, RenomearEditalRequest, UpdateEditalInfoRequest
from utils import sql_paginate, today_str

router = APIRouter(prefix="", tags=["Edital"])


@router.get("/api/edital/nomes", summary="Hierarquia de editais", description="Lista todos os concursos e cargos com contagens de tópicos")
def list_edital_nomes(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista hierarquia: concursos > cargos com contagens (apenas não-arquivados)"""
    rows = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos
        FROM edital WHERE user_id = ? AND arquivado = 0 GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """, (user_id,)).fetchall()
    tree = {}
    for r in rows:
        concurso = r[0]
        if concurso not in tree:
            tree[concurso] = {"concurso": concurso, "cargos": [], "total": 0, "concluidos": 0}
        tree[concurso]["cargos"].append({"cargo": r[1], "total": r[2], "concluidos": r[3]})
        tree[concurso]["total"] += r[2]
        tree[concurso]["concluidos"] += r[3]
    return list(tree.values())


@router.get("/api/edital/info")
def get_edital_info(edital_nome: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna metadados dos editais (datas, locais, horários)"""
    if edital_nome:
        rows = conn.execute("SELECT * FROM edital_info WHERE edital_nome = ? AND user_id = ?", (edital_nome, user_id)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM edital_info WHERE user_id = ? ORDER BY edital_nome, cargo", (user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.put("/api/edital/info/{id}")
def update_edital_info(id: int, body: UpdateEditalInfoRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Atualiza metadados de um edital/cargo"""
    campos = ["edital_nome", "cargo", "orgao", "banca", "vagas", "subsidio", "inscricoes",
              "data_prova_objetiva", "data_prova_discursiva", "horario", "local_prova",
              "taxa_inscricao", "link_edital", "observacoes"]
    sets = []
    params = []
    body_dict = body.model_dump(exclude_unset=True)
    for campo in campos:
        if campo in body_dict:
            sets.append(f"{campo} = ?")
            val = body_dict[campo]
            params.append(sanitize_input(val) if isinstance(val, str) else val)
    if not sets:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    params.append(id)
    params.append(user_id)
    conn.execute(f"UPDATE edital_info SET {', '.join(sets)} WHERE id = ? AND user_id = ?", params)
    conn.commit()
    return {"ok": True, "id": id}


@router.post("/api/edital/info")
def create_edital_info(body: CreateEditalInfoRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Cria metadados para um edital/cargo"""
    cur = conn.execute("""
        INSERT INTO edital_info (edital_nome, cargo, orgao, banca, vagas, subsidio, inscricoes,
            data_prova_objetiva, data_prova_discursiva, horario, local_prova, taxa_inscricao, link_edital, observacoes, user_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sanitize_input(body.edital_nome), sanitize_input(body.cargo), sanitize_input(body.orgao),
          sanitize_input(body.banca), sanitize_input(body.vagas), sanitize_input(body.subsidio),
          sanitize_input(body.inscricoes), sanitize_input(body.data_prova_objetiva),
          sanitize_input(body.data_prova_discursiva), sanitize_input(body.horario),
          sanitize_input(body.local_prova), sanitize_input(body.taxa_inscricao),
          sanitize_input(body.link_edital), sanitize_input(body.observacoes, max_length=2000), user_id))
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.put("/api/edital/renomear")
def renomear_edital(body: RenomearEditalRequest, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Renomeia um edital (atualiza edital_nome em edital e edital_info)"""
    antigo = sanitize_input(body.antigo)
    novo = sanitize_input(body.novo)
    cargo_antigo = sanitize_input(body.cargo_antigo)
    cargo_novo = sanitize_input(body.cargo_novo)

    if not antigo or not novo:
        raise HTTPException(status_code=400, detail="Informe nome antigo e novo")

    # Renomear em edital
    if cargo_antigo and cargo_novo:
        conn.execute("UPDATE edital SET edital_nome = ?, cargo = ? WHERE edital_nome = ? AND cargo = ? AND user_id = ?",
                     (novo, cargo_novo, antigo, cargo_antigo, user_id))
        conn.execute("UPDATE edital_info SET edital_nome = ?, cargo = ? WHERE edital_nome = ? AND cargo = ? AND user_id = ?",
                     (novo, cargo_novo, antigo, cargo_antigo, user_id))
    elif cargo_antigo:
        conn.execute("UPDATE edital SET cargo = ? WHERE edital_nome = ? AND cargo = ? AND user_id = ?",
                     (cargo_novo or cargo_antigo, antigo, cargo_antigo, user_id))
    else:
        conn.execute("UPDATE edital SET edital_nome = ? WHERE edital_nome = ? AND user_id = ?", (novo, antigo, user_id))
        conn.execute("UPDATE edital_info SET edital_nome = ? WHERE edital_nome = ? AND user_id = ?", (novo, antigo, user_id))

    conn.commit()
    return {"ok": True}


@router.get("/api/edital/arquivados")
def list_editais_arquivados(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista editais/cargos que foram arquivados"""
    try:
        rows = conn.execute("""
            SELECT edital_nome, cargo, COUNT(*) as total
            FROM edital WHERE arquivado = 1 AND user_id = ?
            GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
        """, (user_id,)).fetchall()
    except Exception as e:
        log.warning(f"Could not query archived editais: {e}")
        rows = []
    return [{"edital_nome": r[0], "cargo": r[1], "total": r[2]} for r in rows]


@router.get("/api/edital", summary="Listar tópicos do edital", description="Retorna todos os tópicos do edital, com filtros opcionais e paginação")
def list_edital(edital_nome: str = "", cargo: str = "", incluir_arquivados: bool = False, page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT id, edital_nome, cargo, materia, topico, status, horas_estudadas, pdf_link, pdf_pagina, video_link FROM edital WHERE user_id = ?"
    params = [user_id]
    if not incluir_arquivados:
        query += " AND (arquivado IS NULL OR arquivado = 0)"
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " ORDER BY edital_nome, cargo, materia, id"

    return sql_paginate(conn, query, tuple(params), page, limit)


@router.post("/api/edital", summary="Criar tópico", description="Adiciona um novo tópico ao edital verticalizado")
def create_edital(body: EditalCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("INSERT INTO edital (edital_nome, cargo, materia, topico, user_id) VALUES (?, ?, ?, ?, ?)",
                       (body.edital_nome, body.cargo, body.materia, body.topico, user_id))
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Edital topic created: id={new_id} materia={body.materia}")
    return {"id": new_id, "edital_nome": body.edital_nome, "cargo": body.cargo, "materia": body.materia,
            "topico": body.topico, "status": "Não Iniciado", "horas_estudadas": 0.0}


@router.put("/api/edital/{id}/status")
def toggle_edital_status(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cycle = ["Não Iniciado", "Em Andamento", "Concluído"]
    row = conn.execute("SELECT status FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    current = row[0]
    next_status = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else cycle[0]
    conn.execute("UPDATE edital SET status = ? WHERE id = ? AND user_id = ?", (next_status, id, user_id))
    conn.commit()
    return {"id": id, "status": next_status}


@router.put("/api/edital/{id}/horas")
def add_edital_horas(id: int, body: EditalHoras, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT horas_estudadas, materia FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    new_horas = row[0] + body.horas
    conn.execute("UPDATE edital SET horas_estudadas = ? WHERE id = ? AND user_id = ?", (new_horas, id, user_id))
    # Registrar sessão de estudo
    conn.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'edital', ?)",
                 (row[1], body.horas, today_str(), user_id))
    # Atualizar streak do dia
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas, user_id) VALUES (?, ?, ?)
        ON CONFLICT(user_id, data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, user_id, body.horas))
    conn.commit()
    return {"id": id, "horas_estudadas": new_horas}


@router.delete("/api/edital/excluir-edital")
def excluir_edital_inteiro(edital_nome: str, cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Exclui permanentemente todos os tópicos de um edital/cargo"""
    query = "DELETE FROM edital WHERE edital_nome = ? AND user_id = ?"
    params = [edital_nome, user_id]
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    result = conn.execute(query, params)
    # Também remover info
    query2 = "DELETE FROM edital_info WHERE edital_nome = ? AND user_id = ?"
    params2 = [edital_nome, user_id]
    if cargo:
        query2 += " AND cargo = ?"
        params2.append(cargo)
    conn.execute(query2, params2)
    conn.commit()
    count = result.rowcount
    log.info(f"Edital excluído: {edital_nome} ({count} tópicos)")
    return {"ok": True, "excluidos": count}


@router.delete("/api/edital/{id}", response_model=OkResponse)
def delete_edital(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM edital WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    log.info(f"Edital topic deleted: id={id}")
    return {"ok": True}


@router.put("/api/edital/{id}/pdf")
def link_pdf_to_edital(id: int, body: EditalPdfLink, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Vincula um PDF (e página) a um tópico do edital"""
    conn.execute("UPDATE edital SET pdf_link = ?, pdf_pagina = ? WHERE id = ? AND user_id = ?",
                 (body.pdf_link, body.pdf_pagina, id, user_id))
    conn.commit()
    return {"ok": True, "pdf_link": body.pdf_link, "pdf_pagina": body.pdf_pagina}


@router.put("/api/edital/{id}/video")
def link_video_to_edital(id: int, body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Vincula um vídeo YouTube a um tópico do edital."""
    video_link = body.get("video_link", "").strip()
    # Validar que é um link YouTube válido
    if video_link and "youtu" not in video_link and "youtube" not in video_link:
        raise HTTPException(status_code=400, detail="Link deve ser do YouTube.")
    conn.execute("UPDATE edital SET video_link = ? WHERE id = ? AND user_id = ?",
                 (video_link, id, user_id))
    conn.commit()
    return {"ok": True, "video_link": video_link}


@router.post("/api/edital/{id}/video-session")
def register_video_session(id: int, body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Registra tempo assistido de vídeo como sessão de estudo."""
    from datetime import date
    from utils import today_str

    minutos = body.get("minutos", 0)
    if minutos < 1:
        raise HTTPException(status_code=400, detail="Tempo mínimo: 1 minuto.")

    # Buscar matéria do tópico
    topico = conn.execute("SELECT materia, topico FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not topico:
        raise HTTPException(status_code=404, detail="Tópico não encontrado.")

    horas = round(minutos / 60, 3)
    materia = topico["materia"]

    # Registrar sessão de estudo
    conn.execute(
        "INSERT INTO sessoes_estudo (materia, horas, data, tipo, created_at, user_id) VALUES (?, ?, ?, 'video', datetime('now'), ?)",
        (materia, horas, today_str(), user_id)
    )

    # Atualizar horas no edital
    conn.execute("UPDATE edital SET horas_estudadas = horas_estudadas + ? WHERE id = ? AND user_id = ?", (horas, id, user_id))

    # Atualizar streak do dia
    existing = conn.execute("SELECT id FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    if existing:
        conn.execute("UPDATE streaks SET horas_estudadas = horas_estudadas + ? WHERE data = ? AND user_id = ?", (horas, today_str(), user_id))
    else:
        conn.execute("INSERT INTO streaks (data, horas_estudadas, questoes_resolvidas, flashcards_revisados, user_id) VALUES (?, ?, 0, 0, ?)", (today_str(), horas, user_id))

    conn.commit()
    return {"ok": True, "horas": horas, "materia": materia}


@router.put("/api/edital/vincular-bulk")
def vincular_pdf_bulk(materia: str, pdf_link: str, edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Vincula um PDF a todos os tópicos de uma matéria de uma vez"""
    query = "UPDATE edital SET pdf_link = ? WHERE materia = ? AND user_id = ?"
    params = [pdf_link, materia, user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    return {"ok": True, "atualizados": count}


@router.put("/api/edital/desvincular-pdf")
def desvincular_pdf(pdf_link: str, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Remove o vínculo de um PDF de todos os tópicos"""
    result = conn.execute("UPDATE edital SET pdf_link = '', pdf_pagina = 0 WHERE pdf_link = ? AND user_id = ?", (pdf_link, user_id))
    conn.commit()
    count = result.rowcount
    return {"ok": True, "desvinculados": count}


@router.put("/api/edital/arquivar")
def arquivar_edital(edital_nome: str, cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Arquiva um edital/cargo inteiro (marca como arquivado)"""
    query = "UPDATE edital SET arquivado = 1 WHERE edital_nome = ? AND user_id = ?"
    params = [edital_nome, user_id]
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    return {"ok": True, "arquivados": count}


@router.put("/api/edital/desarquivar")
def desarquivar_edital(edital_nome: str, cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Desarquiva um edital/cargo"""
    query = "UPDATE edital SET arquivado = 0 WHERE edital_nome = ? AND user_id = ?"
    params = [edital_nome, user_id]
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    return {"ok": True, "desarquivados": count}



@router.post("/api/edital/importar-pdf")
async def importar_edital_pdf(file: UploadFile = File(...), edital_nome: str = "Importado", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Extrai texto do PDF e tenta identificar matérias/tópicos (versão legacy)"""
    content = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(content)
    tmp.close()

    try:
        reader = PdfReader(tmp.name)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
    except Exception as e:
        os.unlink(tmp.name)
        raise HTTPException(status_code=400, detail=f"Não foi possível ler o PDF: {e}") from e

    os.unlink(tmp.name)

    # Heurística: cada linha com texto relevante vira um tópico
    linhas = [l.strip() for l in text.split('\n') if l.strip() and len(l.strip()) > 5]

    # Agrupar por seções (linhas em maiúsculas ou numeradas são matérias)
    itens = []
    materia_atual = "Geral"
    for linha in linhas:
        if (linha.isupper() and len(linha) < 80) or (len(linha) < 60 and linha[0].isdigit()):
            materia_atual = linha.title()
        elif len(linha) > 10:
            itens.append({"materia": materia_atual, "topico": linha[:200]})

    # Limitar a 100 itens para não sobrecarregar
    itens = itens[:100]

    count = 0
    for item in itens:
        conn.execute("INSERT INTO edital (edital_nome, materia, topico, user_id) VALUES (?, ?, ?, ?)",
                     (edital_nome, item["materia"], item["topico"], user_id))
        count += 1
    conn.commit()

    return {"ok": True, "importados": count, "itens": itens[:20]}


@router.post("/api/edital/importar-pdf-v2")
async def importar_edital_pdf_v2(
    file: UploadFile = File(...),
    edital_nome: str = "",
    cargo_filter: str = "",
    confirmar: bool = False,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """
    Parser inteligente de editais de concursos (v2).

    Extrai verticalização completa do PDF: cargos, matérias e tópicos numerados.

    Parâmetros:
    - file: PDF do edital
    - edital_nome: Nome do edital (opcional, auto-detectado do PDF)
    - cargo_filter: Filtrar por cargo específico (número ou nome parcial)
    - confirmar: Se False (default), retorna preview sem importar.
                 Se True, importa os tópicos no banco.

    Retorna:
    - Preview mode: {edital_nome, total_cargos, total_topicos, cargos: [...]}
    - Import mode: {ok, edital_nome, importados, cargos_importados}
    """
    from edital_parser import parse_edital_pdf

    content = await file.read()
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    tmp.write(content)
    tmp.close()

    try:
        result = parse_edital_pdf(tmp.name)
    except Exception as e:
        os.unlink(tmp.name)
        raise HTTPException(status_code=400, detail=f"Erro ao processar PDF: {e}") from e

    os.unlink(tmp.name)

    # Use provided name or auto-detected
    nome = edital_nome.strip() if edital_nome.strip() else result["edital_nome"]

    # Filter cargos if requested
    cargos_to_import = result["cargos"]
    if cargo_filter:
        cargo_filter_lower = cargo_filter.lower()
        cargos_to_import = [
            c for c in cargos_to_import
            if cargo_filter_lower in c["cargo_numero"].lower()
            or cargo_filter_lower in c["cargo_nome"].lower()
        ]

    if not confirmar:
        # Preview mode: return cargos + disciplinas + metadados
        preview = {
            "edital_nome": nome,
            "total_cargos": len(cargos_to_import),
            "total_materias": result["total_materias"],
            "total_topicos": sum(
                len(t) for c in cargos_to_import for m in c["materias"] for t in [m["topicos"]]
            ),
            "metadados": result.get("metadados", {}),
            "conhecimentos_gerais": [
                {"disciplina": s["disciplina"], "total_topicos": len(s["topicos"])}
                for s in result.get("conhecimentos_gerais", [])
            ],
            "cargos": [
                {
                    "cargo_numero": c["cargo_numero"],
                    "cargo": c["cargo_nome"],
                    "materias": [m["materia"] for m in c["materias"]],
                    "total_topicos": sum(len(m["topicos"]) for m in c["materias"])
                }
                for c in cargos_to_import
            ]
        }
        return preview

    # Import mode: salvar cada tópico individual (mesmo padrão do PC-MA/TCE-MA existentes)
    count = 0
    cargos_importados = []
    for cargo in cargos_to_import:
        cargo_display = cargo["cargo_nome"]
        cargo_count = 0
        for materia in cargo["materias"]:
            for topico in materia["topicos"]:
                conn.execute(
                    "INSERT INTO edital (edital_nome, cargo, materia, topico, user_id) VALUES (?, ?, ?, ?, ?)",
                    (nome, cargo_display, materia["materia"], topico, user_id)
                )
                count += 1
                cargo_count += 1
        cargos_importados.append({"cargo": cargo_display, "topicos_importados": cargo_count})

    # Salvar metadados do concurso em edital_info (por cargo)
    metadados = result.get("metadados", {})
    if metadados:
        for cargo in cargos_to_import:
            cargo_nome = cargo["cargo_nome"]
            existing = conn.execute(
                "SELECT id FROM edital_info WHERE edital_nome = ? AND cargo = ? AND user_id = ?",
                (nome, cargo_nome, user_id)
            ).fetchone()
            if not existing:
                # Determinar data da prova para este cargo
                data_prova = metadados.get("data_prova_objetiva", "")
                datas_provas = metadados.get("datas_provas", [])
                if len(datas_provas) > 1 and ("Auditor" in cargo_nome or "Técnico" in cargo_nome):
                    # Segunda data geralmente é para Auditor/Técnico
                    datas_provas.sort()
                    data_prova = datas_provas[-1] if len(datas_provas) > 1 else data_prova

                conn.execute("""
                    INSERT INTO edital_info (edital_nome, cargo, orgao, banca, vagas, subsidio,
                        inscricoes, data_prova_objetiva, data_prova_discursiva, horario,
                        local_prova, taxa_inscricao, link_edital, observacoes, user_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    nome, cargo_nome,
                    metadados.get("orgao", ""),
                    metadados.get("banca", ""),
                    metadados.get("vagas", {}).get(cargo.get("cargo_numero", ""), "+ CR"),
                    metadados.get("remuneracao", ""),
                    metadados.get("inscricoes", ""),
                    data_prova,
                    metadados.get("data_prova_discursiva", data_prova),
                    "",
                    metadados.get("local_prova", ""),
                    metadados.get("taxa_inscricao", ""),
                    metadados.get("link_edital", ""),
                    f"{metadados.get('escolaridade', '')}. Jornada: {metadados.get('jornada', '')}." if metadados.get("jornada") else metadados.get("escolaridade", ""),
                    user_id
                ))

    conn.commit()
    log.info(f"Edital PDF v2 imported: {nome} - {count} tópicos, {len(cargos_importados)} cargos")

    return {
        "ok": True,
        "edital_nome": nome,
        "importados": count,
        "cargos_importados": cargos_importados
    }




# ============================================================
# MAPAS MENTAIS — Geração automática (Mermaid.js)
# ============================================================

@router.get("/api/edital/mapa-mental", summary="Gerar mapa mental de uma matéria",
            description="Gera código Mermaid.js para visualização de mapa mental dos tópicos de uma matéria.")
def gerar_mapa_mental(
    materia: str,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera mapa mental (Mermaid mindmap) dos tópicos de uma matéria com status."""
    topicos = conn.execute("""
        SELECT id, topico, status, horas_estudadas, mastery_level
        FROM edital
        WHERE materia = ? AND user_id = ? AND arquivado = 0
        ORDER BY id
    """, (materia, user_id)).fetchall()

    if not topicos:
        return {"mermaid": "", "mensagem": f"Nenhum tópico encontrado para '{materia}'."}

    # Gerar código Mermaid mindmap
    # Agrupar por subtemas (primeiro nível numérico)
    grupos = {}
    for t in topicos:
        topico_texto = t["topico"]
        # Tentar extrair grupo pelo número/prefixo (ex: "1 Direito Constitucional", "1.1 Princípios")
        match = re.match(r'^(\d+(?:\.\d+)?)\s*[-–.]?\s*(.+)', topico_texto)
        if match:
            num = match.group(1)
            nome = match.group(2).strip()
            grupo_num = num.split('.')[0]
        else:
            nome = topico_texto
            grupo_num = "0"

        if grupo_num not in grupos:
            grupos[grupo_num] = []
        grupos[grupo_num].append({
            "id": t["id"],
            "nome": nome[:60],  # Limitar tamanho
            "status": t["status"],
            "mastery": t["mastery_level"] or 0,
        })

    # Construir Mermaid mindmap
    lines = ["mindmap"]
    lines.append(f"  root(({materia}))")

    for grupo_num, items in grupos.items():
        if len(items) == 1:
            # Item solto: direto como filho do root
            item = items[0]
            icon = _status_icon(item["status"])
            lines.append(f"    {icon} {item['nome']}")
        else:
            # Grupo com subitens
            primeiro = items[0]
            grupo_nome = primeiro["nome"].split(':')[0].split('-')[0].strip()[:40]
            lines.append(f"    {grupo_nome}")
            for item in items:
                icon = _status_icon(item["status"])
                lines.append(f"      {icon} {item['nome'][:50]}")

    mermaid_code = "\n".join(lines)

    # Também gerar formato flowchart para visualização alternativa
    flow_lines = ["graph TD"]
    flow_lines.append(f'  ROOT["{materia}"]')

    for i, t in enumerate(topicos[:20]):  # Limitar a 20 para não explodir
        node_id = f"T{t['id']}"
        status = t["status"]
        nome_curto = t["topico"][:40].replace('"', "'")

        if status == "Concluído":
            style = f'style {node_id} fill:#a6e3a1,color:#1e1e2e'
        elif status == "Em andamento":
            style = f'style {node_id} fill:#89b4fa,color:#1e1e2e'
        else:
            style = f'style {node_id} fill:#45475a,color:#cdd6f4'

        flow_lines.append(f'  ROOT --> {node_id}["{nome_curto}"]')
        flow_lines.append(f'  {style}')

    flowchart_code = "\n".join(flow_lines)

    # Stats para contexto
    total = len(topicos)
    concluidos = sum(1 for t in topicos if t["status"] == "Concluído")
    em_andamento = sum(1 for t in topicos if t["status"] == "Em andamento")

    return {
        "materia": materia,
        "mermaid_mindmap": mermaid_code,
        "mermaid_flowchart": flowchart_code,
        "stats": {
            "total": total,
            "concluidos": concluidos,
            "em_andamento": em_andamento,
            "nao_iniciados": total - concluidos - em_andamento,
            "pct_concluido": round(concluidos / total * 100, 1) if total > 0 else 0,
        },
        "render_url": f"https://mermaid.ink/svg/{_encode_mermaid(mermaid_code)}",
    }


def _status_icon(status: str) -> str:
    if status == "Concluído":
        return "✅"
    elif status == "Em andamento":
        return "🔵"
    return "⬜"


def _encode_mermaid(code: str) -> str:
    """Encode Mermaid code for mermaid.ink URL."""
    import base64
    return base64.urlsafe_b64encode(code.encode()).decode()


@router.get("/api/edital/mapas-mentais-disponiveis", summary="Listar matérias com mapas mentais disponíveis")
def mapas_mentais_disponiveis(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista matérias que têm tópicos suficientes para gerar mapa mental."""
    materias = conn.execute("""
        SELECT materia, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos
        FROM edital WHERE user_id = ? AND arquivado = 0
        GROUP BY materia HAVING total >= 3
        ORDER BY total DESC
    """, (user_id,)).fetchall()

    return [{
        "materia": m["materia"],
        "total_topicos": m["total"],
        "concluidos": m["concluidos"],
        "pct": round(m["concluidos"] / m["total"] * 100, 1),
    } for m in materias]

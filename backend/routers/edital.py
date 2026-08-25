import os
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
from utils import paginate, sql_paginate, today_str

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
    query = "SELECT id, edital_nome, cargo, materia, topico, status, horas_estudadas, pdf_link, pdf_pagina FROM edital WHERE user_id = ?"
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


@router.get("/api/edital/{id}/notas")
def get_notas_topico(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM notas_topico WHERE edital_id = ? AND user_id = ? ORDER BY created_at DESC", (id, user_id)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/edital/{id}/notas")
def add_nota_topico(id: int, body: NotaTopicoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute("INSERT INTO notas_topico (edital_id, conteudo, created_at, user_id) VALUES (?, ?, ?, ?)",
                       (id, body.conteudo, datetime.now().isoformat(), user_id))
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas-topico/{id}", response_model=OkResponse)
def delete_nota_topico(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM notas_topico WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


@router.post("/api/edital/{id}/agendar-revisao")
def agendar_revisao_topico(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Agenda revisão do tópico usando SM-2 com quality=4 (acertou) por default"""
    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")

    intervalo = row[0] or 1
    ef = row[1] if row[1] is not None else SM2_INITIAL_EF
    reps = row[2] if row[2] is not None else 0
    quality = 4  # default: acertou

    # SM-2 Algorithm
    if reps == 0:
        intervalo = SM2_FIRST_INTERVAL
    elif reps == 1:
        intervalo = SM2_SECOND_INTERVAL
    else:
        intervalo = round(intervalo * ef)
    reps += 1

    # Atualizar EF
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(SM2_MIN_EF, ef)

    proxima = (date.today() + timedelta(days=intervalo)).isoformat()
    conn.execute(
        "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?, easiness_factor_edital = ?, repetitions_edital = ? WHERE id = ? AND user_id = ?",
        (proxima, intervalo, round(ef, 4), reps, id, user_id)
    )
    conn.commit()
    log.info(f"Edital SM-2 revisao: id={id} quality=4 ef={ef:.4f} reps={reps} interval={intervalo}")
    return {"proxima_revisao": proxima, "intervalo": intervalo, "easiness_factor": round(ef, 4), "repetitions": reps}


@router.post("/api/edital/{id}/revisar-sm2")
def revisar_topico_sm2(id: int, body: EditalReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de tópico do edital usando SM-2 com quality variável (0-5)"""
    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")

    intervalo = row[0] or 1
    ef = row[1] if row[1] is not None else SM2_INITIAL_EF
    reps = row[2] if row[2] is not None else 0
    quality = body.quality

    # SM-2 Algorithm
    if quality >= 3:
        if reps == 0:
            intervalo = SM2_FIRST_INTERVAL
        elif reps == 1:
            intervalo = SM2_SECOND_INTERVAL
        else:
            intervalo = round(intervalo * ef)
        reps += 1
    else:
        reps = 0
        intervalo = 1

    # Atualizar EF
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(SM2_MIN_EF, ef)

    proxima = (date.today() + timedelta(days=intervalo)).isoformat()
    conn.execute(
        "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?, easiness_factor_edital = ?, repetitions_edital = ? WHERE id = ? AND user_id = ?",
        (proxima, intervalo, round(ef, 4), reps, id, user_id)
    )
    conn.commit()

    log.info(f"Edital SM-2 revisar: id={id} quality={quality} ef={ef:.4f} reps={reps} interval={intervalo}")
    return {
        "id": id,
        "intervalo_dias": intervalo,
        "proxima_revisao": proxima,
        "easiness_factor": round(ef, 4),
        "repetitions": reps,
        "quality": quality
    }


@router.post("/api/edital/{id}/revisar-fsrs", summary="Revisão FSRS de tópico")
def revisar_topico_fsrs(id: int, body: EditalReviewSM2, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Revisão de tópico do edital usando algoritmo FSRS-5.
    quality: 0-5 (mapeado internamente para rating 1-4 do FSRS)
    """
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from fsrs import FSRSCard, review_card, sm2_to_fsrs_rating
    from constants import FSRS_DEFAULT_RETENTION

    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")

    # Try to read FSRS columns
    stability = 0.0
    difficulty = 0.0
    fsrs_state = 0
    try:
        fsrs_row = conn.execute(
            "SELECT stability_edital, difficulty_edital, fsrs_state_edital FROM edital WHERE id = ? AND user_id = ?", (id, user_id)
        ).fetchone()
        if fsrs_row:
            stability = fsrs_row[0] or 0.0
            difficulty = fsrs_row[1] or 0.0
            fsrs_state = fsrs_row[2] or 0
    except Exception:
        pass

    # Get desired_retention from user's metas_config
    desired_retention = FSRS_DEFAULT_RETENTION
    try:
        meta_row = conn.execute(
            "SELECT desired_retention FROM metas_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if meta_row and meta_row[0]:
            desired_retention = meta_row[0]
    except Exception:
        pass

    # Build FSRS card state
    reps = row[2] if row[2] is not None else 0
    card = FSRSCard(
        stability=stability,
        difficulty=difficulty,
        state=fsrs_state,
        reps=reps
    )

    # Map SM-2 quality (0-5) to FSRS rating (1-4)
    rating = sm2_to_fsrs_rating(body.quality)

    # Call FSRS algorithm
    output = review_card(card, rating, desired_retention=desired_retention)

    proxima = (date.today() + timedelta(days=output.interval)).isoformat()
    new_reps = reps + 1

    # Update edital with FSRS results
    try:
        conn.execute(
            """UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?,
               stability_edital = ?, difficulty_edital = ?, fsrs_state_edital = ?, repetitions_edital = ?
               WHERE id = ? AND user_id = ?""",
            (proxima, output.interval, round(output.stability, 6),
             round(output.difficulty, 4), output.state, new_reps, id, user_id)
        )
    except Exception:
        # Fallback if FSRS columns don't exist
        conn.execute(
            "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ? WHERE id = ? AND user_id = ?",
            (proxima, output.interval, id, user_id)
        )

    conn.commit()

    log.info(f"Edital FSRS revisar: id={id} rating={rating} S={output.stability:.4f} D={output.difficulty:.4f} I={output.interval}")
    return {
        "id": id,
        "intervalo_dias": output.interval,
        "proxima_revisao": proxima,
        "stability": round(output.stability, 6),
        "difficulty": round(output.difficulty, 4),
        "fsrs_state": output.state,
        "repetitions": new_reps,
        "rating": rating,
        "retrievability": round(output.retrievability, 4) if output.retrievability else None
    }


@router.get("/api/edital/revisoes-pendentes")
def revisoes_pendentes(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Lista tópicos com revisão pendente (SRS)"""
    try:
        rows = conn.execute("""
            SELECT id, edital_nome, cargo, materia, topico, proxima_revisao
            FROM edital
            WHERE proxima_revisao != '' AND proxima_revisao <= ? AND user_id = ?
            ORDER BY proxima_revisao
        """, (today_str(), user_id)).fetchall()
    except Exception as e:
        log.warning(f"Could not query pending reviews: {e}")
        rows = []
    return [dict(r) for r in rows]


# ============================================================
# Resumos (Elaboration Strategy)
# ============================================================

@router.get("/api/edital/{id}/resumo")
def get_resumos(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna resumos do tópico do edital"""
    log.info(f"GET /api/edital/{id}/resumo")
    rows = conn.execute(
        "SELECT * FROM resumos WHERE edital_id = ? AND user_id = ? ORDER BY created_at DESC", (id, user_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/edital/{id}/resumo")
def create_resumo(id: int, body: ResumoCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Cria resumo para um tópico do edital"""
    log.info(f"POST /api/edital/{id}/resumo tipo={body.tipo}")
    # Verificar se edital_id existe
    row = conn.execute("SELECT id FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    cur = conn.execute(
        "INSERT INTO resumos (edital_id, resumo, tipo, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
        (id, body.resumo, body.tipo, datetime.now().isoformat(), user_id)
    )
    conn.commit()
    new_id = cur.lastrowid
    return {"id": new_id, "ok": True}


@router.delete("/api/resumos/{id}", response_model=OkResponse)
def delete_resumo(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Exclui um resumo"""
    log.info(f"DELETE /api/resumos/{id}")
    conn.execute("DELETE FROM resumos WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


@router.get("/api/edital/{id}/prompt-resumo")
def prompt_resumo(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna um prompt para o usuário escrever um resumo usando elaboration strategy"""
    log.info(f"GET /api/edital/{id}/prompt-resumo")
    row = conn.execute("SELECT materia, topico FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")

    materia = row[0]
    topico = row[1]

    return {
        "materia": materia,
        "topico": topico,
        "prompt": f"Explique em 3 frases simples o que você aprendeu sobre '{topico}'. Imagine que está explicando para alguém que nunca estudou o assunto.",
        "dicas": [
            "Use suas próprias palavras",
            "Inclua um exemplo prático",
            "Conecte com outro conceito que você conhece"
        ]
    }


# ============================================================
# Exportação
# ============================================================
import csv
import io
import json

from fastapi.responses import Response


@router.get("/api/edital/exportar", summary="Exportar edital verticalizado",
            description="Exporta o edital em formato JSON ou CSV")
def exportar_edital(
    formato: str = "json",
    edital_nome: str = "",
    cargo: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Formatos: json, csv"""
    query = """SELECT id, edital_nome, cargo, materia, topico, status, horas_estudadas, pdf_link, pdf_pagina
               FROM edital WHERE (arquivado IS NULL OR arquivado = 0) AND user_id = ?"""
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " ORDER BY edital_nome, cargo, materia, id"
    rows = conn.execute(query, params).fetchall()
    items = [dict(r) for r in rows]

    if formato == "csv":
        output = io.StringIO()
        if items:
            writer = csv.DictWriter(output, fieldnames=items[0].keys())
            writer.writeheader()
            writer.writerows(items)
        content = output.getvalue()
        return Response(
            content=content,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=edital_verticalizado.csv"}
        )

    # JSON (default) - incluir metadados dos cargos
    # Buscar metadados
    meta_query = "SELECT * FROM edital_info WHERE user_id = ?"
    meta_params = [user_id]
    if edital_nome:
        meta_query += " AND edital_nome = ?"
        meta_params.append(edital_nome)
    if cargo:
        meta_query += " AND cargo = ?"
        meta_params.append(cargo)
    meta_rows = conn.execute(meta_query, meta_params).fetchall()
    metadados = [dict(r) for r in meta_rows]

    export_data = {
        "editais": items,
        "metadados": metadados,
        "total_topicos": len(items),
        "total_cargos": len(metadados)
    }
    content = json.dumps(export_data, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=edital_verticalizado.json"}
    )


@router.post("/api/edital/importar", summary="Importar edital verticalizado",
             description="Importa edital de arquivo JSON ou CSV")
def importar_edital(file: UploadFile = File(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Aceita JSON (array de objetos ou {editais:[], metadados:[]}) ou CSV com colunas: edital_nome, cargo, materia, topico, status, horas_estudadas"""
    content = file.file.read()
    text = content.decode("utf-8")
    items = []
    metadados = []

    if file.filename.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            items.append(row)
    else:
        # JSON
        try:
            data = json.loads(text)
        except Exception:
            raise HTTPException(status_code=400, detail="Arquivo JSON inválido") from None

        # Suportar formato novo {editais:[], metadados:[]} e formato antigo (array direto)
        if isinstance(data, dict) and "editais" in data:
            items = data["editais"]
            metadados = data.get("metadados", [])
        elif isinstance(data, list):
            items = data
        else:
            raise HTTPException(status_code=400, detail="Formato inválido: esperado array ou {editais:[], metadados:[]}")

    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Formato inválido: esperado array de objetos")

    count = 0
    for item in items:
        edital_nome = item.get("edital_nome", "Importado")
        cargo = item.get("cargo", "")
        materia = item.get("materia", "")
        topico = item.get("topico", "")
        status = item.get("status", "Não Iniciado")
        horas = float(item.get("horas_estudadas", 0))
        if not materia or not topico:
            continue
        conn.execute(
            "INSERT INTO edital (edital_nome, cargo, materia, topico, status, horas_estudadas, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (edital_nome, cargo, materia, topico, status, horas, user_id)
        )
        count += 1

    # Importar metadados (se presentes)
    meta_count = 0
    for m in metadados:
        edital_n = m.get("edital_nome", "")
        cargo_n = m.get("cargo", "")
        if not edital_n:
            continue
        # Evitar duplicatas
        existing = conn.execute("SELECT COUNT(*) FROM edital_info WHERE edital_nome = ? AND cargo = ? AND user_id = ?", (edital_n, cargo_n, user_id)).fetchone()[0]
        if existing == 0:
            conn.execute("""
                INSERT INTO edital_info (edital_nome, cargo, orgao, banca, vagas, subsidio, inscricoes,
                    data_prova_objetiva, data_prova_discursiva, horario, local_prova, taxa_inscricao, link_edital, observacoes, user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (edital_n, cargo_n, m.get("orgao",""), m.get("banca",""), m.get("vagas",""),
                  m.get("subsidio",""), m.get("inscricoes",""), m.get("data_prova_objetiva",""),
                  m.get("data_prova_discursiva",""), m.get("horario",""), m.get("local_prova",""),
                  m.get("taxa_inscricao",""), m.get("link_edital",""), m.get("observacoes",""), user_id))
            meta_count += 1

    conn.commit()
    log.info(f"Edital imported: {count} items, {meta_count} metadados")
    return {"ok": True, "importados": count, "metadados_importados": meta_count}


# ============================================================
# MASTERY SYSTEM: nível de domínio por tópico
# ============================================================

def _mastery_label(level: float) -> str:
    """Converte mastery_level numérico em label textual."""
    if level <= 20:
        return "Não Dominado"
    elif level <= 50:
        return "Em Progresso"
    elif level <= 80:
        return "Dominado"
    else:
        return "Consolidado"


def _update_single_mastery(conn, edital_id: int, user_id: int):
    """Recalcula mastery para um único tópico do edital."""
    topic = conn.execute(
        "SELECT id, materia, topico FROM edital WHERE id = ? AND user_id = ?",
        (edital_id, user_id)
    ).fetchone()
    if not topic:
        return

    materia = topic["materia"]
    topico = topic["topico"]

    # Buscar respostas relacionadas a esse tópico
    rows = conn.execute("""
        SELECT qr.acertou, qr.data
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND (q.topico LIKE ? OR q.materia = ?)
        ORDER BY qr.data DESC
    """, (user_id, f'%{topico}%', materia)).fetchall()

    if not rows:
        # Sem dados: mastery = 0
        conn.execute(
            "UPDATE edital SET mastery_level = 0, mastery_updated_at = ? WHERE id = ? AND user_id = ?",
            (today_str(), edital_id, user_id)
        )
        return

    total = len(rows)
    acertos = sum(1 for r in rows if r["acertou"])

    # base_accuracy: percentual de acerto (0-100)
    base_accuracy = (acertos / total) * 100

    # recency_factor: decaimento com base na última revisão
    last_date_str = rows[0]["data"] if rows else ""
    days_since = 0
    if last_date_str:
        try:
            last_date = date.fromisoformat(last_date_str)
            days_since = (date.today() - last_date).days
        except (ValueError, TypeError):
            days_since = 30
    recency_factor = max(0.3, 1.0 - days_since * 0.02)

    # volume_factor: confiança baseada no número de questões
    volume_factor = min(1.0, total / 10)

    # Mastery final
    mastery = base_accuracy * recency_factor * volume_factor
    mastery = max(0, min(100, round(mastery, 2)))

    conn.execute(
        "UPDATE edital SET mastery_level = ?, mastery_updated_at = ? WHERE id = ? AND user_id = ?",
        (mastery, today_str(), edital_id, user_id)
    )


@router.get("/api/edital/mastery-overview", summary="Visão geral de mastery",
            description="Retorna níveis de domínio de todos os tópicos, agrupados por matéria")
def mastery_overview(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna mastery levels para todos os tópicos, agrupados por matéria.
    Se nenhum filtro é passado, usa o edital vinculado ao ciclo ativo."""

    # Auto-detectar edital do ciclo ativo se nenhum filtro explícito
    if not edital_nome and not cargo:
        try:
            # Selecionar o edital com MAIS matérias em comum com o ciclo ativo
            ciclo_edital = conn.execute("""
                SELECT e.edital_nome, COUNT(DISTINCT e.materia) as matches
                FROM edital e
                INNER JOIN ciclo_estudos c ON c.materia = e.materia AND c.user_id = e.user_id
                WHERE c.ativo = 1 AND c.user_id = ? AND e.arquivado = 0
                GROUP BY e.edital_nome
                ORDER BY matches DESC
                LIMIT 1
            """, (user_id,)).fetchone()
            if ciclo_edital and ciclo_edital[0]:
                edital_nome = ciclo_edital[0]
        except Exception:
            pass

    query = "SELECT id, materia, topico, mastery_level, mastery_updated_at FROM edital WHERE user_id = ? AND arquivado = 0"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " ORDER BY materia, topico"

    rows = conn.execute(query, params).fetchall()

    # Agrupar por matéria
    materias_map = {}
    for r in rows:
        mat = r["materia"]
        if mat not in materias_map:
            materias_map[mat] = {"materia": mat, "topics": [], "total_mastery": 0.0}
        level = r["mastery_level"] or 0
        materias_map[mat]["topics"].append({
            "id": r["id"],
            "topico": r["topico"],
            "mastery_level": round(level, 2),
            "mastery_label": _mastery_label(level),
            "mastery_updated_at": r["mastery_updated_at"] or "",
        })
        materias_map[mat]["total_mastery"] += level

    # Calcular média por matéria
    result = []
    for mat_data in materias_map.values():
        n_topics = len(mat_data["topics"])
        avg = mat_data["total_mastery"] / n_topics if n_topics > 0 else 0
        result.append({
            "materia": mat_data["materia"],
            "avg_mastery": round(avg, 2),
            "avg_mastery_label": _mastery_label(avg),
            "topics": mat_data["topics"],
        })

    # Ordenar por menor mastery primeiro (mais urgentes no topo)
    result.sort(key=lambda x: x["avg_mastery"])

    return {"materias": result}


@router.post("/api/edital/mastery/recalculate", summary="Recalcular mastery de todos os tópicos",
             description="Recalcula mastery para todos os tópicos baseado em desempenho + decaimento temporal")
def recalculate_mastery(edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Recalcula mastery para todos os tópicos baseado em performance + time decay."""
    query = "SELECT id FROM edital WHERE user_id = ? AND arquivado = 0"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)

    topics = conn.execute(query, params).fetchall()
    updated = 0
    for topic in topics:
        _update_single_mastery(conn, topic["id"], user_id)
        updated += 1

    conn.commit()
    log.info(f"Mastery recalculated for {updated} topics (user={user_id})")
    return {"ok": True, "updated": updated}


@router.post("/api/edital/{id}/mastery-update", summary="Atualizar mastery de um tópico",
             description="Recalcula mastery para um único tópico. Chamado após responder questões.")
def update_mastery_single(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Recalcula mastery para um único tópico."""
    topic = conn.execute("SELECT id FROM edital WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not topic:
        raise HTTPException(status_code=404, detail="Tópico não encontrado")

    _update_single_mastery(conn, id, user_id)
    conn.commit()

    # Retornar o valor atualizado
    updated = conn.execute(
        "SELECT mastery_level, mastery_updated_at FROM edital WHERE id = ? AND user_id = ?",
        (id, user_id)
    ).fetchone()
    level = updated["mastery_level"] or 0
    return {
        "ok": True,
        "id": id,
        "mastery_level": round(level, 2),
        "mastery_label": _mastery_label(level),
        "mastery_updated_at": updated["mastery_updated_at"] or "",
    }

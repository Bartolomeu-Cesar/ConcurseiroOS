import os
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pypdf import PdfReader

from constants import SM2_FIRST_INTERVAL, SM2_INITIAL_EF, SM2_MIN_EF, SM2_SECOND_INTERVAL
from database import get_db_session
from logger import log
from models import EditalCreate, EditalHoras, EditalPdfLink, EditalReviewSM2, NotaTopicoCreate, OkResponse, ResumoCreate
from utils import paginate, today_str

router = APIRouter(prefix="", tags=["Edital"])


@router.get("/api/edital/nomes", summary="Hierarquia de editais", description="Lista todos os concursos e cargos com contagens de tópicos")
def list_edital_nomes(conn=Depends(get_db_session)):
    """Lista hierarquia: concursos > cargos com contagens"""
    rows = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos
        FROM edital GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """).fetchall()
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
def get_edital_info(edital_nome: str = "", conn=Depends(get_db_session)):
    """Retorna metadados dos editais (datas, locais, horários)"""
    if edital_nome:
        rows = conn.execute("SELECT * FROM edital_info WHERE edital_nome = ?", (edital_nome,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM edital_info ORDER BY edital_nome, cargo").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/edital/arquivados")
def list_editais_arquivados(conn=Depends(get_db_session)):
    """Lista editais/cargos que foram arquivados"""
    try:
        rows = conn.execute("""
            SELECT edital_nome, cargo, COUNT(*) as total
            FROM edital WHERE arquivado = 1
            GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
        """).fetchall()
    except Exception as e:
        log.warning(f"Could not query archived editais: {e}")
        rows = []
    return [{"edital_nome": r[0], "cargo": r[1], "total": r[2]} for r in rows]


@router.get("/api/edital", summary="Listar tópicos do edital", description="Retorna todos os tópicos do edital, com filtros opcionais e paginação")
def list_edital(edital_nome: str = "", cargo: str = "", incluir_arquivados: bool = False, page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session)):
    query = "SELECT id, edital_nome, cargo, materia, topico, status, horas_estudadas, pdf_link, pdf_pagina FROM edital WHERE 1=1"
    params = []
    if not incluir_arquivados:
        query += " AND (arquivado IS NULL OR arquivado = 0)"
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    query += " ORDER BY edital_nome, cargo, materia, id"
    rows = conn.execute(query, params).fetchall()

    items = [dict(r) for r in rows]
    return paginate(items, page, limit)


@router.post("/api/edital", summary="Criar tópico", description="Adiciona um novo tópico ao edital verticalizado")
def create_edital(body: EditalCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO edital (edital_nome, cargo, materia, topico) VALUES (?, ?, ?, ?)",
                       (body.edital_nome, body.cargo, body.materia, body.topico))
    conn.commit()
    new_id = cur.lastrowid
    log.info(f"Edital topic created: id={new_id} materia={body.materia}")
    return {"id": new_id, "edital_nome": body.edital_nome, "cargo": body.cargo, "materia": body.materia,
            "topico": body.topico, "status": "Não Iniciado", "horas_estudadas": 0.0}


@router.put("/api/edital/{id}/status")
def toggle_edital_status(id: int, conn=Depends(get_db_session)):
    cycle = ["Não Iniciado", "Em Andamento", "Concluído"]
    row = conn.execute("SELECT status FROM edital WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    current = row[0]
    next_status = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else cycle[0]
    conn.execute("UPDATE edital SET status = ? WHERE id = ?", (next_status, id))
    conn.commit()
    return {"id": id, "status": next_status}


@router.put("/api/edital/{id}/horas")
def add_edital_horas(id: int, body: EditalHoras, conn=Depends(get_db_session)):
    row = conn.execute("SELECT horas_estudadas, materia FROM edital WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    new_horas = row[0] + body.horas
    conn.execute("UPDATE edital SET horas_estudadas = ? WHERE id = ?", (new_horas, id))
    # Registrar sessão de estudo
    conn.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo) VALUES (?, ?, ?, 'edital')",
                 (row[1], body.horas, today_str()))
    # Atualizar streak do dia
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas) VALUES (?, ?)
        ON CONFLICT(data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, body.horas))
    conn.commit()
    return {"id": id, "horas_estudadas": new_horas}


@router.delete("/api/edital/{id}", response_model=OkResponse)
def delete_edital(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM edital WHERE id = ?", (id,))
    conn.commit()
    log.info(f"Edital topic deleted: id={id}")
    return {"ok": True}


@router.put("/api/edital/{id}/pdf")
def link_pdf_to_edital(id: int, body: EditalPdfLink, conn=Depends(get_db_session)):
    """Vincula um PDF (e página) a um tópico do edital"""
    conn.execute("UPDATE edital SET pdf_link = ?, pdf_pagina = ? WHERE id = ?",
                 (body.pdf_link, body.pdf_pagina, id))
    conn.commit()
    return {"ok": True, "pdf_link": body.pdf_link, "pdf_pagina": body.pdf_pagina}


@router.put("/api/edital/vincular-bulk")
def vincular_pdf_bulk(materia: str, pdf_link: str, edital_nome: str = "", cargo: str = "", conn=Depends(get_db_session)):
    """Vincula um PDF a todos os tópicos de uma matéria de uma vez"""
    query = "UPDATE edital SET pdf_link = ? WHERE materia = ?"
    params = [pdf_link, materia]
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
def desvincular_pdf(pdf_link: str, conn=Depends(get_db_session)):
    """Remove o vínculo de um PDF de todos os tópicos"""
    result = conn.execute("UPDATE edital SET pdf_link = '', pdf_pagina = 0 WHERE pdf_link = ?", (pdf_link,))
    conn.commit()
    count = result.rowcount
    return {"ok": True, "desvinculados": count}


@router.put("/api/edital/arquivar")
def arquivar_edital(edital_nome: str, cargo: str = "", conn=Depends(get_db_session)):
    """Arquiva um edital/cargo inteiro (marca como arquivado)"""
    query = "UPDATE edital SET arquivado = 1 WHERE edital_nome = ?"
    params = [edital_nome]
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    return {"ok": True, "arquivados": count}


@router.put("/api/edital/desarquivar")
def desarquivar_edital(edital_nome: str, cargo: str = "", conn=Depends(get_db_session)):
    """Desarquiva um edital/cargo"""
    query = "UPDATE edital SET arquivado = 0 WHERE edital_nome = ?"
    params = [edital_nome]
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    result = conn.execute(query, params)
    conn.commit()
    count = result.rowcount
    return {"ok": True, "desarquivados": count}


@router.delete("/api/edital/excluir-edital")
def excluir_edital_inteiro(edital_nome: str, cargo: str = "", conn=Depends(get_db_session)):
    """Exclui permanentemente todos os tópicos de um edital/cargo"""
    query = "DELETE FROM edital WHERE edital_nome = ?"
    params = [edital_nome]
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    result = conn.execute(query, params)
    # Também remover info
    query2 = "DELETE FROM edital_info WHERE edital_nome = ?"
    params2 = [edital_nome]
    if cargo:
        query2 += " AND cargo = ?"
        params2.append(cargo)
    conn.execute(query2, params2)
    conn.commit()
    count = result.rowcount
    return {"ok": True, "excluidos": count}


@router.post("/api/edital/importar-pdf")
async def importar_edital_pdf(file: UploadFile = File(...), edital_nome: str = "Importado", conn=Depends(get_db_session)):
    """Extrai texto do PDF e tenta identificar matérias/tópicos"""
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
        conn.execute("INSERT INTO edital (edital_nome, materia, topico) VALUES (?, ?, ?)",
                     (edital_nome, item["materia"], item["topico"]))
        count += 1
    conn.commit()

    return {"ok": True, "importados": count, "itens": itens[:20]}


@router.get("/api/edital/{id}/notas")
def get_notas_topico(id: int, conn=Depends(get_db_session)):
    rows = conn.execute("SELECT * FROM notas_topico WHERE edital_id = ? ORDER BY created_at DESC", (id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/edital/{id}/notas")
def add_nota_topico(id: int, body: NotaTopicoCreate, conn=Depends(get_db_session)):
    cur = conn.execute("INSERT INTO notas_topico (edital_id, conteudo, created_at) VALUES (?, ?, ?)",
                       (id, body.conteudo, datetime.now().isoformat()))
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas-topico/{id}", response_model=OkResponse)
def delete_nota_topico(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM notas_topico WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}


@router.post("/api/edital/{id}/agendar-revisao")
def agendar_revisao_topico(id: int, conn=Depends(get_db_session)):
    """Agenda revisão do tópico usando SM-2 com quality=4 (acertou) por default"""
    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ?", (id,)
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
        "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?, easiness_factor_edital = ?, repetitions_edital = ? WHERE id = ?",
        (proxima, intervalo, round(ef, 4), reps, id)
    )
    conn.commit()
    log.info(f"Edital SM-2 revisao: id={id} quality=4 ef={ef:.4f} reps={reps} interval={intervalo}")
    return {"proxima_revisao": proxima, "intervalo": intervalo, "easiness_factor": round(ef, 4), "repetitions": reps}


@router.post("/api/edital/{id}/revisar-sm2")
def revisar_topico_sm2(id: int, body: EditalReviewSM2, conn=Depends(get_db_session)):
    """Revisão de tópico do edital usando SM-2 com quality variável (0-5)"""
    row = conn.execute(
        "SELECT intervalo_revisao, easiness_factor_edital, repetitions_edital FROM edital WHERE id = ?", (id,)
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
        "UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ?, easiness_factor_edital = ?, repetitions_edital = ? WHERE id = ?",
        (proxima, intervalo, round(ef, 4), reps, id)
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


@router.get("/api/edital/revisoes-pendentes")
def revisoes_pendentes(conn=Depends(get_db_session)):
    """Lista tópicos com revisão pendente (SRS)"""
    try:
        rows = conn.execute("""
            SELECT id, edital_nome, cargo, materia, topico, proxima_revisao
            FROM edital
            WHERE proxima_revisao != '' AND proxima_revisao <= ?
            ORDER BY proxima_revisao
        """, (today_str(),)).fetchall()
    except Exception as e:
        log.warning(f"Could not query pending reviews: {e}")
        rows = []
    return [dict(r) for r in rows]


# ============================================================
# Resumos (Elaboration Strategy)
# ============================================================

@router.get("/api/edital/{id}/resumo")
def get_resumos(id: int, conn=Depends(get_db_session)):
    """Retorna resumos do tópico do edital"""
    log.info(f"GET /api/edital/{id}/resumo")
    rows = conn.execute(
        "SELECT * FROM resumos WHERE edital_id = ? ORDER BY created_at DESC", (id,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/edital/{id}/resumo")
def create_resumo(id: int, body: ResumoCreate, conn=Depends(get_db_session)):
    """Cria resumo para um tópico do edital"""
    log.info(f"POST /api/edital/{id}/resumo tipo={body.tipo}")
    # Verificar se edital_id existe
    row = conn.execute("SELECT id FROM edital WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Tópico do edital não encontrado")
    cur = conn.execute(
        "INSERT INTO resumos (edital_id, resumo, tipo, created_at) VALUES (?, ?, ?, ?)",
        (id, body.resumo, body.tipo, datetime.now().isoformat())
    )
    conn.commit()
    new_id = cur.lastrowid
    return {"id": new_id, "ok": True}


@router.delete("/api/resumos/{id}", response_model=OkResponse)
def delete_resumo(id: int, conn=Depends(get_db_session)):
    """Exclui um resumo"""
    log.info(f"DELETE /api/resumos/{id}")
    conn.execute("DELETE FROM resumos WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}


@router.get("/api/edital/{id}/prompt-resumo")
def prompt_resumo(id: int, conn=Depends(get_db_session)):
    """Retorna um prompt para o usuário escrever um resumo usando elaboration strategy"""
    log.info(f"GET /api/edital/{id}/prompt-resumo")
    row = conn.execute("SELECT materia, topico FROM edital WHERE id = ?", (id,)).fetchone()
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
    conn=Depends(get_db_session)
):
    """Formatos: json, csv"""
    query = """SELECT id, edital_nome, cargo, materia, topico, status, horas_estudadas, pdf_link, pdf_pagina
               FROM edital WHERE (arquivado IS NULL OR arquivado = 0)"""
    params = []
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

    # JSON (default)
    content = json.dumps(items, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=edital_verticalizado.json"}
    )

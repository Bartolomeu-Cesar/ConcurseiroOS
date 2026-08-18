import os
import tempfile
import math
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pypdf import PdfReader

from database import get_db
from logger import log
from models import EditalCreate, EditalHoras, EditalPdfLink, NotaTopicoCreate
from utils import today_str

router = APIRouter(prefix="", tags=["Edital"])


@router.get("/api/edital/nomes", summary="Hierarquia de editais", description="Lista todos os concursos e cargos com contagens de tópicos")
def list_edital_nomes():
    """Lista hierarquia: concursos > cargos com contagens"""
    with get_db() as conn:
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
def get_edital_info(edital_nome: str = ""):
    """Retorna metadados dos editais (datas, locais, horários)"""
    with get_db() as conn:
        if edital_nome:
            rows = conn.execute("SELECT * FROM edital_info WHERE edital_nome = ?", (edital_nome,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM edital_info ORDER BY edital_nome, cargo").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/edital/arquivados")
def list_editais_arquivados():
    """Lista editais/cargos que foram arquivados"""
    with get_db() as conn:
        try:
            rows = conn.execute("""
                SELECT edital_nome, cargo, COUNT(*) as total
                FROM edital WHERE arquivado = 1
                GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
            """).fetchall()
        except Exception:
            rows = []
    return [{"edital_nome": r[0], "cargo": r[1], "total": r[2]} for r in rows]


@router.get("/api/edital", summary="Listar tópicos do edital", description="Retorna todos os tópicos do edital, com filtros opcionais e paginação")
def list_edital(edital_nome: str = "", cargo: str = "", incluir_arquivados: bool = False, page: Optional[int] = Query(None), limit: int = 50):
    with get_db() as conn:
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

    # Se page não fornecido, retorna array completo (retrocompatibilidade)
    if page is None:
        return items

    # Paginação
    total = len(items)
    pages = math.ceil(total / limit) if limit > 0 else 1
    start = (page - 1) * limit
    end = start + limit
    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": pages
    }


@router.post("/api/edital", summary="Criar tópico", description="Adiciona um novo tópico ao edital verticalizado")
def create_edital(body: EditalCreate):
    with get_db() as conn:
        cur = conn.execute("INSERT INTO edital (edital_nome, cargo, materia, topico) VALUES (?, ?, ?, ?)",
                           (body.edital_nome, body.cargo, body.materia, body.topico))
        conn.commit()
        new_id = cur.lastrowid
    log.info(f"Edital topic created: id={new_id} materia={body.materia}")
    return {"id": new_id, "edital_nome": body.edital_nome, "cargo": body.cargo, "materia": body.materia,
            "topico": body.topico, "status": "Não Iniciado", "horas_estudadas": 0.0}


@router.put("/api/edital/{id}/status")
def toggle_edital_status(id: int):
    cycle = ["Não Iniciado", "Em Andamento", "Concluído"]
    with get_db() as conn:
        row = conn.execute("SELECT status FROM edital WHERE id = ?", (id,)).fetchone()
        if not row:
            raise HTTPException(404)
        current = row[0]
        next_status = cycle[(cycle.index(current) + 1) % len(cycle)] if current in cycle else cycle[0]
        conn.execute("UPDATE edital SET status = ? WHERE id = ?", (next_status, id))
        conn.commit()
    return {"id": id, "status": next_status}


@router.put("/api/edital/{id}/horas")
def add_edital_horas(id: int, body: EditalHoras):
    with get_db() as conn:
        row = conn.execute("SELECT horas_estudadas, materia FROM edital WHERE id = ?", (id,)).fetchone()
        if not row:
            raise HTTPException(404)
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


@router.delete("/api/edital/{id}")
def delete_edital(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM edital WHERE id = ?", (id,))
        conn.commit()
    log.info(f"Edital topic deleted: id={id}")
    return {"ok": True}


@router.put("/api/edital/{id}/pdf")
def link_pdf_to_edital(id: int, body: EditalPdfLink):
    """Vincula um PDF (e página) a um tópico do edital"""
    with get_db() as conn:
        conn.execute("UPDATE edital SET pdf_link = ?, pdf_pagina = ? WHERE id = ?",
                     (body.pdf_link, body.pdf_pagina, id))
        conn.commit()
    return {"ok": True, "pdf_link": body.pdf_link, "pdf_pagina": body.pdf_pagina}


@router.put("/api/edital/vincular-bulk")
def vincular_pdf_bulk(materia: str, pdf_link: str, edital_nome: str = "", cargo: str = ""):
    """Vincula um PDF a todos os tópicos de uma matéria de uma vez"""
    with get_db() as conn:
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
def desvincular_pdf(pdf_link: str):
    """Remove o vínculo de um PDF de todos os tópicos"""
    with get_db() as conn:
        result = conn.execute("UPDATE edital SET pdf_link = '', pdf_pagina = 0 WHERE pdf_link = ?", (pdf_link,))
        conn.commit()
        count = result.rowcount
    return {"ok": True, "desvinculados": count}


@router.put("/api/edital/arquivar")
def arquivar_edital(edital_nome: str, cargo: str = ""):
    """Arquiva um edital/cargo inteiro (marca como arquivado)"""
    with get_db() as conn:
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
def desarquivar_edital(edital_nome: str, cargo: str = ""):
    """Desarquiva um edital/cargo"""
    with get_db() as conn:
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
def excluir_edital_inteiro(edital_nome: str, cargo: str = ""):
    """Exclui permanentemente todos os tópicos de um edital/cargo"""
    with get_db() as conn:
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
async def importar_edital_pdf(file: UploadFile = File(...), edital_nome: str = "Importado"):
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
    except Exception:
        os.unlink(tmp.name)
        raise HTTPException(400, "Não foi possível ler o PDF")

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

    with get_db() as conn:
        count = 0
        for item in itens:
            conn.execute("INSERT INTO edital (edital_nome, materia, topico) VALUES (?, ?, ?)",
                         (edital_nome, item["materia"], item["topico"]))
            count += 1
        conn.commit()

    return {"ok": True, "importados": count, "itens": itens[:20]}


@router.get("/api/edital/{id}/notas")
def get_notas_topico(id: int):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM notas_topico WHERE edital_id = ? ORDER BY created_at DESC", (id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/edital/{id}/notas")
def add_nota_topico(id: int, body: NotaTopicoCreate):
    from datetime import datetime
    with get_db() as conn:
        cur = conn.execute("INSERT INTO notas_topico (edital_id, conteudo, created_at) VALUES (?, ?, ?)",
                           (id, body.conteudo, datetime.now().isoformat()))
        conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/notas-topico/{id}")
def delete_nota_topico(id: int):
    with get_db() as conn:
        conn.execute("DELETE FROM notas_topico WHERE id = ?", (id,))
        conn.commit()
    return {"ok": True}


@router.post("/api/edital/{id}/agendar-revisao")
def agendar_revisao_topico(id: int):
    """Agenda revisão do tópico usando SRS (dobra intervalo a cada revisão)"""
    with get_db() as conn:
        row = conn.execute("SELECT intervalo_revisao FROM edital WHERE id = ?", (id,)).fetchone()
        if not row:
            raise HTTPException(404)
        intervalo = (row[0] or 1) * 2
        proxima = (date.today() + timedelta(days=intervalo)).isoformat()
        conn.execute("UPDATE edital SET proxima_revisao = ?, intervalo_revisao = ? WHERE id = ?",
                     (proxima, intervalo, id))
        conn.commit()
    return {"proxima_revisao": proxima, "intervalo": intervalo}


@router.get("/api/edital/revisoes-pendentes")
def revisoes_pendentes():
    """Lista tópicos com revisão pendente (SRS)"""
    with get_db() as conn:
        try:
            rows = conn.execute("""
                SELECT id, edital_nome, cargo, materia, topico, proxima_revisao
                FROM edital
                WHERE proxima_revisao != '' AND proxima_revisao <= ?
                ORDER BY proxima_revisao
            """, (today_str(),)).fetchall()
        except Exception:
            rows = []
    return [dict(r) for r in rows]

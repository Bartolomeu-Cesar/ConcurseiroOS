"""Resumos, exportação/importação e mastery."""
import json
import os
import tempfile
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile

from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import OkResponse, ResumoCreate
from sanitize import sanitize_input
from utils import today_str

router = APIRouter(prefix="", tags=["Edital"])

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
            if ciclo_edital and ciclo_edital["edital_nome"]:
                edital_nome = ciclo_edital["edital_nome"]
        except Exception:
            pass

    query = "SELECT DISTINCT id, materia, topico, mastery_level, mastery_updated_at FROM edital WHERE user_id = ? AND arquivado = 0"
    params = [user_id]
    if edital_nome:
        query += " AND edital_nome = ?"
        params.append(edital_nome)
    if cargo:
        query += " AND cargo = ?"
        params.append(cargo)
    else:
        # Se não tem cargo explícito, filtrar por matérias do ciclo ativo (evita duplicatas entre cargos)
        try:
            ciclo_materias = conn.execute(
                "SELECT DISTINCT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
            ).fetchall()
            if ciclo_materias:
                placeholders = ",".join("?" * len(ciclo_materias))
                query += f" AND materia IN ({placeholders})"
                params.extend([m["materia"] for m in ciclo_materias])
        except Exception:
            pass
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

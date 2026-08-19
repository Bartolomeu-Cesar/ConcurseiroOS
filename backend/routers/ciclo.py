from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from database import get_db_session
from logger import log
from models import CicloCreate, CicloHoras, CicloUpdate
from utils import today_str

router = APIRouter(prefix="", tags=["Ciclo de Estudos"])


@router.get("/api/ciclo")
def list_ciclo(conn=Depends(get_db_session)):
    rows = conn.execute("SELECT * FROM ciclo_estudos ORDER BY ordem, id").fetchall()
    return [dict(r) for r in rows]


@router.get("/api/ciclo/proximo")
def proximo_ciclo(conn=Depends(get_db_session)):
    """Retorna a próxima matéria a estudar no ciclo (menor % cumprido)"""
    rows = conn.execute("""
        SELECT *, (horas_cumpridas / horas_alvo) as progresso
        FROM ciclo_estudos WHERE ativo = 1
        ORDER BY progresso ASC, ordem ASC LIMIT 1
    """).fetchone()
    if rows:
        return dict(rows)
    return {"materia": "Nenhuma matéria no ciclo", "horas_alvo": 0, "horas_cumpridas": 0}


@router.post("/api/ciclo")
def create_ciclo(body: CicloCreate, conn=Depends(get_db_session)):
    max_ordem = conn.execute("SELECT COALESCE(MAX(ordem), 0) FROM ciclo_estudos").fetchone()[0]
    cur = conn.execute("INSERT INTO ciclo_estudos (materia, horas_alvo, ordem) VALUES (?, ?, ?)",
                       (body.materia, body.horas_alvo, max_ordem + 1))
    conn.commit()
    new_id = cur.lastrowid
    return {"id": new_id, "ok": True}


@router.post("/api/ciclo/resetar")
def resetar_ciclo(conn=Depends(get_db_session)):
    """Reseta as horas cumpridas de todas as matérias para iniciar novo ciclo"""
    conn.execute("UPDATE ciclo_estudos SET horas_cumpridas = 0")
    conn.commit()
    return {"ok": True}


@router.put("/api/ciclo/{id}")
def update_ciclo(id: int, body: CicloUpdate, conn=Depends(get_db_session)):
    if body.horas_alvo is not None:
        conn.execute("UPDATE ciclo_estudos SET horas_alvo = ? WHERE id = ?", (body.horas_alvo, id))
    if body.ativo is not None:
        conn.execute("UPDATE ciclo_estudos SET ativo = ? WHERE id = ?", (body.ativo, id))
    if body.ordem is not None:
        conn.execute("UPDATE ciclo_estudos SET ordem = ? WHERE id = ?", (body.ordem, id))
    conn.commit()
    return {"ok": True}


@router.put("/api/ciclo/{id}/horas")
def add_ciclo_horas(id: int, body: CicloHoras, conn=Depends(get_db_session)):
    row = conn.execute("SELECT materia, horas_cumpridas FROM ciclo_estudos WHERE id = ?", (id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Item do ciclo não encontrado")
    new_horas = row[1] + body.horas
    conn.execute("UPDATE ciclo_estudos SET horas_cumpridas = ? WHERE id = ?", (new_horas, id))
    # Registrar sessão
    conn.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo) VALUES (?, ?, ?, 'ciclo')",
                 (row[0], body.horas, today_str()))
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas) VALUES (?, ?)
        ON CONFLICT(data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, body.horas))
    conn.commit()
    return {"id": id, "horas_cumpridas": new_horas}


@router.delete("/api/ciclo/{id}")
def delete_ciclo(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM ciclo_estudos WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}


# ============================================================
# Exportação
# ============================================================
import csv
import io
import json

from fastapi.responses import Response


@router.get("/api/ciclo/exportar", summary="Exportar ciclo de estudos",
            description="Exporta o ciclo de estudos em formato JSON ou CSV")
def exportar_ciclo(formato: str = "json", conn=Depends(get_db_session)):
    """Formatos: json, csv"""
    rows = conn.execute("SELECT id, materia, horas_alvo, horas_cumpridas, ordem, ativo FROM ciclo_estudos ORDER BY ordem, id").fetchall()
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
            headers={"Content-Disposition": "attachment; filename=ciclo_estudos.csv"}
        )

    content = json.dumps(items, ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=ciclo_estudos.json"}
    )


@router.post("/api/ciclo/importar", summary="Importar ciclo de estudos",
             description="Importa ciclo de arquivo JSON ou CSV")
def importar_ciclo(file: UploadFile = File(...), conn=Depends(get_db_session)):
    """Aceita JSON (array) ou CSV com colunas: materia, horas_alvo, horas_cumpridas, ordem, ativo"""
    content = file.file.read()
    text = content.decode("utf-8")
    items = []

    if file.filename.endswith(".csv"):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            items.append(row)
    else:
        try:
            items = json.loads(text)
        except Exception:
            raise HTTPException(status_code=400, detail="Arquivo JSON inválido") from None

    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="Formato inválido: esperado array de objetos")

    count = 0
    for item in items:
        materia = item.get("materia", "")
        if not materia:
            continue
        horas_alvo = float(item.get("horas_alvo", 1.0))
        horas_cumpridas = float(item.get("horas_cumpridas", 0.0))
        ordem = int(item.get("ordem", count))
        ativo = int(item.get("ativo", 1))
        conn.execute(
            "INSERT INTO ciclo_estudos (materia, horas_alvo, horas_cumpridas, ordem, ativo) VALUES (?, ?, ?, ?, ?)",
            (materia, horas_alvo, horas_cumpridas, ordem, ativo)
        )
        count += 1
    conn.commit()
    log.info(f"Ciclo imported: {count} items")
    return {"ok": True, "importados": count}

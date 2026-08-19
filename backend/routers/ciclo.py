from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from database import get_db_session
from logger import log
from models import CicloCreate, CicloHoras, CicloUpdate
from utils import today_str

router = APIRouter(prefix="", tags=["Ciclo de Estudos"])


# ============================================================
# GERAÇÃO AUTOMÁTICA DO CICLO (SCORING INTELIGENTE)
# ============================================================

def _calcular_score_materia(materia: str, conn) -> dict:
    """
    Calcula o score de prioridade de uma matéria para o ciclo.
    Fatores:
    - Tópicos pendentes (mais pendentes = mais importante para aprovação)
    - Desempenho em questões (pior acerto = precisa reforçar)
    - Horas já estudadas vs peso no edital (pouco estudo = precisa mais)
    - Dias sem estudar (mais dias = precisa revisão urgente)
    - Matéria nunca estudada = prioridade máxima
    """
    # 1. Tópicos pendentes vs total
    topicos = conn.execute("""
        SELECT COUNT(*) as total,
               SUM(CASE WHEN status != 'Concluído' THEN 1 ELSE 0 END) as pendentes
        FROM edital WHERE materia = ? AND arquivado = 0
    """, (materia,)).fetchone()
    total_topicos = topicos[0] or 1
    pendentes = topicos[1] or 0
    pct_pendente = pendentes / total_topicos  # 0.0 a 1.0

    # 2. Desempenho em questões
    desempenho = conn.execute("""
        SELECT COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE q.materia = ?
    """, (materia,)).fetchone()
    total_questoes = desempenho[0] or 0
    acertos = desempenho[1] or 0
    pct_acerto = (acertos / total_questoes * 100) if total_questoes > 0 else 0
    # Penalizar falta de questões (nunca praticou = risco)
    fator_pratica = 1.0 if total_questoes >= 10 else 1.3 if total_questoes == 0 else 1.1

    # 3. Horas já estudadas
    horas = conn.execute("""
        SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ?
    """, (materia,)).fetchone()[0]

    # 4. Dias sem estudar
    ultima_sessao = conn.execute("""
        SELECT MAX(data) FROM sessoes_estudo WHERE materia = ?
    """, (materia,)).fetchone()[0]
    if ultima_sessao:
        try:
            dias_sem = (date.today() - date.fromisoformat(ultima_sessao)).days
        except (ValueError, TypeError):
            dias_sem = 30
    else:
        dias_sem = 999  # Nunca estudou

    # ============ SCORING ============
    # Score alto = mais prioridade = mais horas no ciclo
    score = 0.0

    # Peso do edital: matérias com mais tópicos pendentes são mais críticas
    score += pct_pendente * 40  # 0-40 pontos

    # Desempenho ruim = precisa reforçar
    score += (100 - pct_acerto) * 0.3 * fator_pratica  # 0-39 pontos

    # Dias sem estudar: penalização crescente
    if dias_sem >= 999:
        score += 20  # Nunca estudou = prioridade alta
    elif dias_sem >= 14:
        score += 15
    elif dias_sem >= 7:
        score += 10
    elif dias_sem >= 3:
        score += 5

    # Pouco estudo acumulado para uma matéria pesada
    horas_esperadas = total_topicos * 0.5  # ~30min por tópico como mínimo
    if horas_esperadas > 0 and horas < horas_esperadas:
        deficit = (horas_esperadas - horas) / horas_esperadas
        score += deficit * 10  # 0-10 pontos

    return {
        "materia": materia,
        "score": round(score, 2),
        "total_topicos": total_topicos,
        "pendentes": pendentes,
        "pct_acerto": round(pct_acerto, 1),
        "total_questoes": total_questoes,
        "horas_estudadas": round(horas, 1),
        "dias_sem_estudar": dias_sem if dias_sem < 999 else None,
    }


def _gerar_ciclo_automatico(conn, horas_dia: float = 3.0) -> dict:
    """Gera ciclo automaticamente a partir dos editais com scoring inteligente.
    Retorna info sobre o ciclo gerado."""
    # Buscar todas as matérias ativas no edital
    materias = conn.execute("""
        SELECT DISTINCT materia FROM edital
        WHERE arquivado = 0 AND materia != ''
    """).fetchall()

    if not materias:
        return {"ok": False, "erro": "Nenhuma matéria encontrada no edital", "gerados": 0}

    # Calcular score de cada matéria
    scored = []
    for row in materias:
        info = _calcular_score_materia(row[0], conn)
        scored.append(info)

    # Ordenar por score (maior prioridade primeiro)
    scored.sort(key=lambda x: -x["score"])

    # Limpar ciclo existente
    conn.execute("DELETE FROM ciclo_estudos")

    # Converter scores em horas_alvo proporcionais
    # Score mais alto = mais horas. Mínimo 0.5h, máximo proporcional ao total disponível
    total_score = sum(m["score"] for m in scored) or 1
    total_horas_semana = horas_dia * 6  # 6 dias úteis

    for i, m in enumerate(scored):
        # Proporção do score → horas na semana → horas por ciclo (alvo)
        proporcao = m["score"] / total_score
        horas_alvo = max(0.5, round(proporcao * total_horas_semana, 1))
        # Cap em 4h para não dominar
        horas_alvo = min(4.0, horas_alvo)

        conn.execute(
            "INSERT INTO ciclo_estudos (materia, horas_alvo, horas_cumpridas, ordem, ativo) VALUES (?, ?, 0, ?, 1)",
            (m["materia"], horas_alvo, i + 1)
        )

    conn.commit()
    log.info(f"Ciclo auto-gerado: {len(scored)} matérias")

    return {
        "ok": True,
        "gerados": len(scored),
        "horas_dia": horas_dia,
        "materias": scored[:10],  # Top 10 para referência
    }


@router.post("/api/ciclo/gerar-automatico", summary="Gerar ciclo automaticamente",
             description="Analisa editais, desempenho e dificuldades para gerar ciclo inteligente")
def gerar_ciclo_automatico(horas_dia: float = Query(default=3.0), conn=Depends(get_db_session)):
    """Gera ciclo de estudos baseado em:
    - Matérias com mais tópicos pendentes (críticas para aprovação)
    - Pior desempenho em questões (dificuldades do usuário)
    - Menos horas estudadas / Nunca estudadas (gaps)
    - Mais dias sem estudar (necessidade de revisão)
    """
    result = _gerar_ciclo_automatico(conn, horas_dia)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["erro"])
    return result


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


@router.delete("/api/ciclo/limpar")
def limpar_ciclo(conn=Depends(get_db_session)):
    """Remove TODAS as matérias do ciclo para poder reimportar de outro edital"""
    count = conn.execute("SELECT COUNT(*) FROM ciclo_estudos").fetchone()[0]
    conn.execute("DELETE FROM ciclo_estudos")
    conn.commit()
    return {"ok": True, "removidos": count}


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

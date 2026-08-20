from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from database import get_db_session
from deps import get_user_id
from logger import log
from models import CicloCreate, CicloHoras, CicloUpdate
from utils import today_str

router = APIRouter(prefix="", tags=["Ciclo de Estudos"])


# ============================================================
# GERAÇÃO AUTOMÁTICA DO CICLO (SCORING INTELIGENTE)
# ============================================================

def _calcular_score_materia(materia: str, conn, user_id: int) -> dict:
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
        FROM edital WHERE materia = ? AND arquivado = 0 AND user_id = ?
    """, (materia, user_id)).fetchone()
    total_topicos = topicos[0] or 1
    pendentes = topicos[1] or 0
    pct_pendente = pendentes / total_topicos  # 0.0 a 1.0

    # 2. Desempenho em questões
    desempenho = conn.execute("""
        SELECT COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE q.materia = ? AND qr.user_id = ?
    """, (materia, user_id)).fetchone()
    total_questoes = desempenho[0] or 0
    acertos = desempenho[1] or 0
    pct_acerto = (acertos / total_questoes * 100) if total_questoes > 0 else 0
    # Penalizar falta de questões (nunca praticou = risco)
    fator_pratica = 1.0 if total_questoes >= 10 else 1.3 if total_questoes == 0 else 1.1

    # 3. Horas já estudadas
    horas = conn.execute("""
        SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE materia = ? AND user_id = ?
    """, (materia, user_id)).fetchone()[0]

    # 4. Dias sem estudar
    ultima_sessao = conn.execute("""
        SELECT MAX(data) FROM sessoes_estudo WHERE materia = ? AND user_id = ?
    """, (materia, user_id)).fetchone()[0]
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


def _gerar_ciclo_automatico(conn, user_id: int, horas_dia: float = 3.0) -> dict:
    """Gera ciclo automaticamente a partir dos editais com scoring inteligente.
    Retorna info sobre o ciclo gerado."""
    # Buscar todas as matérias ativas no edital
    materias = conn.execute("""
        SELECT DISTINCT materia FROM edital
        WHERE arquivado = 0 AND materia != '' AND user_id = ?
    """, (user_id,)).fetchall()

    if not materias:
        return {"ok": False, "erro": "Nenhuma matéria encontrada no edital", "gerados": 0}

    # Calcular score de cada matéria
    scored = []
    for row in materias:
        info = _calcular_score_materia(row[0], conn, user_id)
        scored.append(info)

    # Ordenar por score (maior prioridade primeiro)
    scored.sort(key=lambda x: -x["score"])

    # Limpar ciclo existente
    conn.execute("DELETE FROM ciclo_estudos WHERE user_id = ?", (user_id,))

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
            "INSERT INTO ciclo_estudos (materia, horas_alvo, horas_cumpridas, ordem, ativo, user_id) VALUES (?, ?, 0, ?, 1, ?)",
            (m["materia"], horas_alvo, i + 1, user_id)
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
def gerar_ciclo_automatico(horas_dia: float = Query(default=3.0), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera ciclo de estudos baseado em:
    - Matérias com mais tópicos pendentes (críticas para aprovação)
    - Pior desempenho em questões (dificuldades do usuário)
    - Menos horas estudadas / Nunca estudadas (gaps)
    - Mais dias sem estudar (necessidade de revisão)
    """
    result = _gerar_ciclo_automatico(conn, user_id, horas_dia)
    if not result["ok"]:
        raise HTTPException(status_code=400, detail=result["erro"])
    return result


@router.get("/api/ciclo")
def list_ciclo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM ciclo_estudos WHERE user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/ciclo/proximo")
def proximo_ciclo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a próxima matéria a estudar no ciclo (menor % cumprido)"""
    rows = conn.execute("""
        SELECT *, (horas_cumpridas / horas_alvo) as progresso
        FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?
        ORDER BY progresso ASC, ordem ASC LIMIT 1
    """, (user_id,)).fetchone()
    if rows:
        return dict(rows)
    return {"materia": "Nenhuma matéria no ciclo", "horas_alvo": 0, "horas_cumpridas": 0}


@router.post("/api/ciclo")
def create_ciclo(body: CicloCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    max_ordem = conn.execute("SELECT COALESCE(MAX(ordem), 0) FROM ciclo_estudos WHERE user_id = ?", (user_id,)).fetchone()[0]
    cur = conn.execute("INSERT INTO ciclo_estudos (materia, horas_alvo, ordem, user_id) VALUES (?, ?, ?, ?)",
                       (body.materia, body.horas_alvo, max_ordem + 1, user_id))
    conn.commit()
    new_id = cur.lastrowid
    return {"id": new_id, "ok": True}


@router.post("/api/ciclo/resetar")
def resetar_ciclo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Reseta as horas cumpridas de todas as matérias para iniciar novo ciclo"""
    conn.execute("UPDATE ciclo_estudos SET horas_cumpridas = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    return {"ok": True}


@router.delete("/api/ciclo/limpar")
def limpar_ciclo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Remove TODAS as matérias do ciclo para poder reimportar de outro edital"""
    count = conn.execute("SELECT COUNT(*) FROM ciclo_estudos WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.execute("DELETE FROM ciclo_estudos WHERE user_id = ?", (user_id,))
    conn.commit()
    return {"ok": True, "removidos": count}


@router.put("/api/ciclo/{id}")
def update_ciclo(id: int, body: CicloUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    if body.horas_alvo is not None:
        conn.execute("UPDATE ciclo_estudos SET horas_alvo = ? WHERE id = ? AND user_id = ?", (body.horas_alvo, id, user_id))
    if body.ativo is not None:
        conn.execute("UPDATE ciclo_estudos SET ativo = ? WHERE id = ? AND user_id = ?", (body.ativo, id, user_id))
    if body.ordem is not None:
        conn.execute("UPDATE ciclo_estudos SET ordem = ? WHERE id = ? AND user_id = ?", (body.ordem, id, user_id))
    conn.commit()
    return {"ok": True}


@router.put("/api/ciclo/{id}/horas")
def add_ciclo_horas(id: int, body: CicloHoras, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    row = conn.execute("SELECT materia, horas_cumpridas FROM ciclo_estudos WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Item do ciclo não encontrado")
    new_horas = row[1] + body.horas
    conn.execute("UPDATE ciclo_estudos SET horas_cumpridas = ? WHERE id = ? AND user_id = ?", (new_horas, id, user_id))
    # Registrar sessão
    conn.execute("INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id) VALUES (?, ?, ?, 'ciclo', ?)",
                 (row[0], body.horas, today_str(), user_id))
    conn.execute("""
        INSERT INTO streaks (data, horas_estudadas, user_id) VALUES (?, ?, ?)
        ON CONFLICT(data) DO UPDATE SET horas_estudadas = horas_estudadas + ?
    """, (today_str(), body.horas, user_id, body.horas))
    conn.commit()
    return {"id": id, "horas_cumpridas": new_horas}


@router.delete("/api/ciclo/{id}")
def delete_ciclo(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM ciclo_estudos WHERE id = ? AND user_id = ?", (id, user_id))
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
def exportar_ciclo(formato: str = "json", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Formatos: json, csv"""
    rows = conn.execute("SELECT id, materia, horas_alvo, horas_cumpridas, ordem, ativo FROM ciclo_estudos WHERE user_id = ? ORDER BY ordem, id", (user_id,)).fetchall()
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
def importar_ciclo(file: UploadFile = File(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
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
            "INSERT INTO ciclo_estudos (materia, horas_alvo, horas_cumpridas, ordem, ativo, user_id) VALUES (?, ?, ?, ?, ?, ?)",
            (materia, horas_alvo, horas_cumpridas, ordem, ativo, user_id)
        )
        count += 1
    conn.commit()
    log.info(f"Ciclo imported: {count} items")
    return {"ok": True, "importados": count}


# ============================================================
# RESUMO DO DIA ANTERIOR
# ============================================================

@router.get("/api/ciclo/ontem", summary="Resumo do dia anterior",
            description="Retorna o que deveria ter sido estudado ontem (planejador) vs o que foi realmente estudado")
def ciclo_ontem(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Compara o planejado vs realizado do dia anterior para feedback."""
    from datetime import timedelta

    ontem = (date.today() - timedelta(days=1))
    ontem_str = ontem.isoformat()
    dia_semana_ontem = ontem.weekday()  # 0=Seg, 6=Dom

    # O que estava planejado para ontem (do planejador_semanal)
    planejado = conn.execute("""
        SELECT materia, horas FROM planejador_semanal
        WHERE dia_semana = ? AND user_id = ?
        ORDER BY id
    """, (dia_semana_ontem, user_id)).fetchall()

    materias_planejadas = [{"materia": r[0], "horas_planejadas": r[1]} for r in planejado]
    total_planejado = sum(r[1] for r in planejado)

    # O que foi realmente estudado ontem
    estudado = conn.execute("""
        SELECT materia, SUM(horas) as horas
        FROM sessoes_estudo
        WHERE data = ? AND user_id = ?
        GROUP BY materia
    """, (ontem_str, user_id)).fetchall()

    estudado_map = {r[0]: round(r[1], 2) for r in estudado}
    total_estudado = sum(estudado_map.values())

    # Questões resolvidas ontem
    questoes_ontem = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE data = ? AND user_id = ?",
        (ontem_str, user_id)
    ).fetchone()[0]

    # Flashcards revisados ontem
    streak_ontem = conn.execute(
        "SELECT flashcards_revisados FROM streaks WHERE data = ? AND user_id = ?",
        (ontem_str, user_id)
    ).fetchone()
    flashcards_ontem = streak_ontem[0] if streak_ontem else 0

    # Montar comparativo por matéria
    comparativo = []
    for mp in materias_planejadas:
        mat = mp["materia"]
        horas_real = estudado_map.pop(mat, 0)
        pct = round(horas_real / mp["horas_planejadas"] * 100) if mp["horas_planejadas"] > 0 else 0
        status = "✅" if pct >= 80 else "⚠️" if pct >= 40 else "❌"
        comparativo.append({
            "materia": mat,
            "horas_planejadas": mp["horas_planejadas"],
            "horas_estudadas": round(horas_real, 2),
            "pct_cumprido": min(pct, 100),
            "status": status
        })

    # Matérias estudadas fora do plano
    extras = []
    for mat, horas in estudado_map.items():
        extras.append({"materia": mat, "horas_estudadas": round(horas, 2)})

    # Score geral do dia
    if total_planejado > 0:
        score_dia = min(100, round(total_estudado / total_planejado * 100))
    else:
        score_dia = 100 if total_estudado > 0 else 0

    # Mensagem motivacional
    if score_dia >= 90:
        mensagem = "🏆 Excelente! Dia quase perfeito."
    elif score_dia >= 70:
        mensagem = "👏 Bom trabalho! Continue assim."
    elif score_dia >= 40:
        mensagem = "⚠️ Dia parcial. Tente compensar hoje."
    elif total_estudado > 0:
        mensagem = "📖 Estudou pouco ontem. Hoje é dia de recuperar!"
    else:
        mensagem = "❌ Não estudou ontem. Não desanime — comece agora!"

    nomes_dias = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]

    return {
        "data": ontem_str,
        "dia_semana": nomes_dias[dia_semana_ontem],
        "score_dia": score_dia,
        "mensagem": mensagem,
        "total_planejado": round(total_planejado, 1),
        "total_estudado": round(total_estudado, 1),
        "questoes": questoes_ontem,
        "flashcards": flashcards_ontem,
        "comparativo": comparativo,
        "extras": extras,
        "teve_plano": len(materias_planejadas) > 0,
        "estudou": total_estudado > 0
    }

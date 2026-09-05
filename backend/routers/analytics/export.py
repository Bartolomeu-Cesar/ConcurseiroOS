"""Exportação, importação, compartilhamento e widgets."""
import json
import tempfile
from datetime import datetime

from deps import get_user_id
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse

from database import get_db_session
from utils import calculate_streak, sql_paginate, today_str

router = APIRouter(prefix="", tags=["Analytics"])

@router.get("/api/linha-tempo", summary="Linha do tempo")
def linha_tempo(page: int | None = Query(None), limit: int = 50, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT data, materia, horas, tipo FROM sessoes_estudo WHERE user_id = ? ORDER BY data DESC, id DESC"
    if page is None:
        rows = conn.execute(query, (user_id,)).fetchall()
        return [dict(r) for r in rows][:50]
    return sql_paginate(conn, query, (user_id,), page, limit)


@router.get("/api/exportar-stats")
def exportar_estatisticas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    data = {
        "exportado_em": datetime.now().isoformat(),
        "edital": [dict(r) for r in conn.execute("SELECT * FROM edital WHERE user_id = ?", (user_id,)).fetchall()],
        "questoes_stats": {
            "total": conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0],
            "acertos": conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0],
        },
        "sessoes": [dict(r) for r in conn.execute("SELECT * FROM sessoes_estudo WHERE user_id = ? ORDER BY data DESC LIMIT 100", (user_id,)).fetchall()],
        "streaks": [dict(r) for r in conn.execute("SELECT * FROM streaks WHERE user_id = ? ORDER BY data DESC LIMIT 30", (user_id,)).fetchall()],
        "simulados": [dict(r) for r in conn.execute("SELECT * FROM simulados WHERE user_id = ?", (user_id,)).fetchall()],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="estatisticas_completas.json", background=None)


@router.get("/api/exportar-resumo")
def exportar_resumo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    editais = conn.execute("""
        SELECT edital_nome, cargo, COUNT(*) as total,
               SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as done,
               SUM(horas_estudadas) as horas
        FROM edital WHERE user_id = ? GROUP BY edital_nome, cargo ORDER BY edital_nome, cargo
    """, (user_id,)).fetchall()
    q_stats = conn.execute("SELECT COUNT(*), SUM(acertou) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()
    streaks = conn.execute("SELECT data, horas_estudadas, questoes_resolvidas FROM streaks WHERE user_id = ? ORDER BY data DESC LIMIT 30", (user_id,)).fetchall()

    html = f"""<!DOCTYPE html>
<html><head><meta charset='UTF-8'><title>Resumo de Estudos - ConcurseiroOS</title>
<style>
  body {{ font-family: sans-serif; padding: 40px; max-width: 800px; margin: 0 auto; }}
  h1 {{ color: #6c3483; border-bottom: 2px solid #6c3483; padding-bottom: 8px; }}
  h2 {{ color: #2980b9; margin-top: 24px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 12px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 0.9rem; }}
  th {{ background: #f4f4f4; }}
  .stat {{ display: inline-block; margin: 8px 16px 8px 0; padding: 8px 16px; background: #f0f0f0; border-radius: 8px; }}
  .stat strong {{ font-size: 1.3rem; }}
  @media print {{ body {{ padding: 20px; }} }}
</style></head><body>
<h1>📚 Resumo de Estudos - ConcurseiroOS</h1>
<p>Gerado em: {datetime.now().strftime('%d/%m/%Y às %H:%M')}</p>
<h2>📊 Estatísticas Gerais</h2>
<div class='stat'>Questões: <strong>{q_stats[0] or 0}</strong> resolvidas ({q_stats[1] or 0} acertos)</div>
<div class='stat'>Aproveitamento: <strong>{round((q_stats[1]/q_stats[0]*100) if q_stats[0] else 0, 1)}%</strong></div>
<h2>📋 Progresso por Edital/Cargo</h2>
<table><tr><th>Edital</th><th>Cargo</th><th>Tópicos</th><th>Concluídos</th><th>%</th><th>Horas</th></tr>"""
    for e in editais:
        pct = round(e[3] / e[2] * 100, 1) if e[2] > 0 else 0
        html += f"<tr><td>{e[0]}</td><td>{e[1]}</td><td>{e[2]}</td><td>{e[3]}</td><td>{pct}%</td><td>{e[4]:.1f}h</td></tr>"
    html += "</table>"
    if streaks:
        html += "<h2>🔥 Últimos 30 dias de Estudo</h2><table><tr><th>Data</th><th>Horas</th><th>Questões</th></tr>"
        for s in streaks:
            html += f"<tr><td>{s[0]}</td><td>{s[1]:.1f}h</td><td>{s[2]}</td></tr>"
        html += "</table>"
    html += "</body></html>"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".html", mode="w", encoding="utf-8")
    tmp.write(html)
    tmp.close()
    return FileResponse(tmp.name, media_type="text/html", filename="resumo_estudos.html", background=None)


@router.get("/api/exportar-tudo")
def exportar_tudo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    data = {
        "exportado_em": datetime.now().isoformat(), "versao": "2.0",
        "edital": [dict(r) for r in conn.execute("SELECT * FROM edital WHERE user_id = ?", (user_id,)).fetchall()],
        "questoes": [dict(r) for r in conn.execute("SELECT * FROM questoes WHERE user_id = ?", (user_id,)).fetchall()],
        "flashcards": [dict(r) for r in conn.execute("SELECT * FROM flashcards WHERE user_id = ?", (user_id,)).fetchall()],
        "questoes_respostas": [dict(r) for r in conn.execute("SELECT * FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchall()],
        "sessoes_estudo": [dict(r) for r in conn.execute("SELECT * FROM sessoes_estudo WHERE user_id = ?", (user_id,)).fetchall()],
        "streaks": [dict(r) for r in conn.execute("SELECT * FROM streaks WHERE user_id = ?", (user_id,)).fetchall()],
        "simulados": [dict(r) for r in conn.execute("SELECT * FROM simulados WHERE user_id = ?", (user_id,)).fetchall()],
        "ciclo_estudos": [dict(r) for r in conn.execute("SELECT * FROM ciclo_estudos WHERE user_id = ?", (user_id,)).fetchall()],
        "metas_config": [dict(r) for r in conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchall()],
    }
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".json", mode="w", encoding="utf-8")
    json.dump(data, tmp, ensure_ascii=False, indent=2)
    tmp.close()
    return FileResponse(tmp.name, media_type="application/json", filename="concurseiro_backup_completo.json", background=None)


@router.post("/api/importar-tudo")
async def importar_tudo(file: UploadFile = File(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    content = await file.read()
    try:
        data = json.loads(content)
    except Exception:
        raise HTTPException(status_code=400, detail="JSON inválido") from None

    count = 0
    for item in data.get("flashcards", []):
        conn.execute("INSERT OR IGNORE INTO flashcards (pergunta, resposta, proxima_revisao, intervalo_dias, user_id) VALUES (?, ?, ?, ?, ?)",
                     (item["pergunta"], item["resposta"], item.get("proxima_revisao", today_str()), item.get("intervalo_dias", 1), user_id))
        count += 1
    for item in data.get("questoes", []):
        conn.execute("""INSERT OR IGNORE INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao, dificuldade, created_at, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (item.get("materia", ""), item.get("topico", ""), item.get("enunciado", ""),
             item.get("alternativa_a", ""), item.get("alternativa_b", ""), item.get("alternativa_c", ""),
             item.get("alternativa_d", ""), item.get("alternativa_e", ""), item.get("resposta_correta", ""),
             item.get("explicacao", ""), item.get("dificuldade", "Médio"), item.get("created_at", today_str()), user_id))
        count += 1
    conn.commit()
    return {"ok": True, "importados": count}


@router.get("/api/compartilhar")
def gerar_compartilhamento(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?", (user_id,)).fetchone()[0]
    questoes = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    acertos = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    topicos = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)).fetchone()[0]
    total_topicos = conn.execute("SELECT COUNT(*) FROM edital WHERE user_id = ?", (user_id,)).fetchone()[0]
    streak_info = calculate_streak(conn, user_id)
    streak = streak_info["streak_atual"]
    pct = round(topicos / total_topicos * 100, 1) if total_topicos > 0 else 0
    accuracy = round(acertos / questoes * 100, 1) if questoes > 0 else 0

    return {
        "texto": f"📚 ConcurseiroOS | {streak}🔥 dias | {round(horas, 1)}h estudadas | {questoes} questões ({accuracy}%) | {pct}% do edital",
        "stats": {"horas": round(horas, 1), "questoes": questoes, "accuracy": accuracy,
                  "streak": streak, "topicos": topicos, "total_topicos": total_topicos, "pct_edital": pct}
    }


@router.get("/api/status-rapido")
def status_rapido(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)).fetchone()[0]
    topicos_done = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)).fetchone()[0]
    topicos_total = conn.execute("SELECT COUNT(*) FROM edital WHERE user_id = ?", (user_id,)).fetchone()[0]
    streak_info = calculate_streak(conn, user_id)
    return {
        "streak": streak_info["streak_atual"],
        "horas_hoje": hoje["horas_estudadas"] if hoje else 0,
        "questoes_hoje": hoje["questoes_resolvidas"] if hoje else 0,
        "flashcards_pendentes": flash,
        "edital_pct": round(topicos_done / topicos_total * 100, 1) if topicos_total > 0 else 0,
        "topicos": f"{topicos_done}/{topicos_total}"
    }


@router.get("/api/widget")
def widget_resumo(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    flash = conn.execute("SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)).fetchone()[0]
    try:
        prova = conn.execute("""
            SELECT cargo, data_prova_objetiva FROM edital_info
            WHERE data_prova_objetiva != '' AND data_prova_objetiva != 'Consultar edital' AND user_id = ?
            ORDER BY data_prova_objetiva LIMIT 1
        """, (user_id,)).fetchone()
    except Exception:
        prova = None
    return {
        "streak_hoje": bool(hoje), "horas_hoje": hoje["horas_estudadas"] if hoje else 0,
        "questoes_hoje": hoje["questoes_resolvidas"] if hoje else 0,
        "flashcards_pendentes": flash,
        "proxima_prova": {"cargo": prova[0], "data": prova[1]} if prova else None
    }

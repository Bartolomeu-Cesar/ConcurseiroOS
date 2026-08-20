"""Router do Calendário Personalizado e Atividades."""
import random
from datetime import date, datetime, timedelta
from typing import List

from fastapi import APIRouter, Body, Depends, Query

from database import get_db_session
from logger import log
from models import CalendarioItem
from utils import today_str

router = APIRouter(prefix="", tags=["Calendário"])

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ============================================================
# CALENDÁRIO PERSONALIZADO
# ============================================================

@router.get("/api/calendario-personalizado")
def get_calendario_personalizado(conn=Depends(get_db_session)):
    """Retorna o calendário personalizado salvo pelo usuário."""
    rows = conn.execute(
        "SELECT id, dia_semana, materia, topicos, tempo_min, tipo, ordem FROM calendario_personalizado ORDER BY dia_semana, ordem"
    ).fetchall()
    items = [dict(r) for r in rows]
    dias = []
    for d in range(7):
        atividades = [i for i in items if i["dia_semana"] == d]
        tempo_total = sum(a["tempo_min"] for a in atividades)
        materias = list(set(a["materia"] for a in atividades if a["materia"]))
        dias.append({
            "dia_semana": d, "nome": NOMES_DIAS[d],
            "atividades": atividades, "tempo_total_min": tempo_total, "materias": materias
        })
    return {"dias": dias}


@router.post("/api/calendario-personalizado")
def add_calendario_item(body: CalendarioItem, conn=Depends(get_db_session)):
    cur = conn.execute(
        "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem) VALUES (?, ?, ?, ?, ?, ?)",
        (body.dia_semana, body.materia, body.topicos, body.tempo_min, body.tipo, body.ordem)
    )
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/calendario-personalizado/{id}")
def delete_calendario_item(id: int, conn=Depends(get_db_session)):
    conn.execute("DELETE FROM calendario_personalizado WHERE id = ?", (id,))
    conn.commit()
    return {"ok": True}


@router.delete("/api/calendario-personalizado")
def clear_calendario_personalizado(conn=Depends(get_db_session)):
    conn.execute("DELETE FROM calendario_personalizado")
    conn.commit()
    return {"ok": True}


@router.post("/api/calendario-personalizado/salvar-completo")
def salvar_calendario_completo(dias: list = Body(...), conn=Depends(get_db_session)):
    """Salva o calendário completo (limpa e recria)."""
    conn.execute("DELETE FROM calendario_personalizado")
    count = 0
    for item in dias:
        conn.execute(
            "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem) VALUES (?, ?, ?, ?, ?, ?)",
            (item.get("dia_semana", 0), item.get("materia", ""), item.get("topicos", ""),
             item.get("tempo_min", 60), item.get("tipo", "estudo"), item.get("ordem", count))
        )
        count += 1
    conn.commit()
    return {"ok": True, "salvos": count}


# ============================================================
# ATIVIDADES DO CALENDÁRIO - CONCLUSÃO + STREAK
# ============================================================

@router.post("/api/calendario/atividade-concluida")
def marcar_atividade_concluida(body: dict = Body(...), conn=Depends(get_db_session)):
    """Marca uma atividade do calendário como concluída."""
    data_str = body.get("data", today_str())
    dia_semana = body.get("dia_semana", 0)
    materia = body.get("materia", "")
    tipo = body.get("tipo", "estudo")
    tempo_min = body.get("tempo_min", 0)

    conn.execute("""
        INSERT INTO calendario_atividades (data, dia_semana, materia, tipo, tempo_min, concluida, concluida_at)
        VALUES (?, ?, ?, ?, ?, 1, ?)
    """, (data_str, dia_semana, materia, tipo, tempo_min, datetime.now().isoformat()))

    _update_calendario_streak(conn, data_str, body.get("total_atividades", 0))
    conn.commit()
    log.info(f"Atividade concluída: {materia} ({tipo}) em {data_str}")
    return {"ok": True}


@router.delete("/api/calendario/atividade-concluida")
def desmarcar_atividade_concluida(body: dict = Body(...), conn=Depends(get_db_session)):
    """Desmarca uma atividade (desfaz conclusão)."""
    data_str = body.get("data", today_str())
    materia = body.get("materia", "")
    tipo = body.get("tipo", "estudo")

    conn.execute("""
        DELETE FROM calendario_atividades
        WHERE data = ? AND materia = ? AND tipo = ?
        ORDER BY id DESC LIMIT 1
    """, (data_str, materia, tipo))

    _update_calendario_streak(conn, data_str, body.get("total_atividades", 0))
    conn.commit()
    return {"ok": True}


@router.get("/api/calendario/concluidas")
def get_atividades_concluidas(data: str = "", conn=Depends(get_db_session)):
    """Retorna atividades concluídas de um dia (ou hoje)."""
    data_str = data or today_str()
    rows = conn.execute(
        "SELECT * FROM calendario_atividades WHERE data = ? AND concluida = 1", (data_str,)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/calendario/streak")
def get_calendario_streak(conn=Depends(get_db_session)):
    """Retorna streak de dias com 100% do calendário concluído."""
    rows = conn.execute("""
        SELECT data, pct_conclusao FROM calendario_streaks
        WHERE pct_conclusao >= 100 ORDER BY data DESC
    """).fetchall()

    streak = 0
    hoje = date.today()
    for i, r in enumerate(rows):
        expected = (hoje - timedelta(days=i)).isoformat()
        if r[0] == expected:
            streak += 1
        else:
            break

    best = 0
    current = 0
    all_dates = sorted([r[0] for r in rows])
    for i, d in enumerate(all_dates):
        if i == 0:
            current = 1
        else:
            prev = date.fromisoformat(all_dates[i-1])
            curr = date.fromisoformat(d)
            if (curr - prev).days == 1:
                current += 1
            else:
                current = 1
        best = max(best, current)

    hoje_row = conn.execute("SELECT * FROM calendario_streaks WHERE data = ?", (today_str(),)).fetchone()
    return {
        "streak_calendario": streak,
        "melhor_streak_calendario": best,
        "hoje": dict(hoje_row) if hoje_row else {"total_atividades": 0, "concluidas": 0, "pct_conclusao": 0}
    }


def _update_calendario_streak(conn, data_str: str, total_atividades: int = 0):
    """Atualiza o registro de streak do calendário para uma data."""
    concluidas = conn.execute(
        "SELECT COUNT(*) FROM calendario_atividades WHERE data = ? AND concluida = 1", (data_str,)
    ).fetchone()[0]
    pct = round((concluidas / total_atividades * 100) if total_atividades > 0 else 0, 1)
    xp = 50 if pct >= 100 else 0

    conn.execute("""
        INSERT INTO calendario_streaks (data, total_atividades, concluidas, pct_conclusao, xp_bonus)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(data) DO UPDATE SET
            total_atividades = ?, concluidas = ?, pct_conclusao = ?, xp_bonus = ?
    """, (data_str, total_atividades, concluidas, pct, xp,
          total_atividades, concluidas, pct, xp))


# ============================================================
# ALERTA DE MATÉRIAS NEGLIGENCIADAS
# ============================================================

@router.get("/api/calendario/materias-negligenciadas")
def get_materias_negligenciadas(dias_limite: int = 5, conn=Depends(get_db_session)):
    """Retorna matérias importantes que não foram estudadas há mais de X dias."""
    hoje = date.today()
    materias = conn.execute("""
        SELECT materia, COUNT(*) as pendentes FROM edital
        WHERE status != 'Concluído' GROUP BY materia HAVING pendentes > 3 ORDER BY pendentes DESC
    """).fetchall()

    sessoes = conn.execute("SELECT materia, MAX(data) as ultima FROM sessoes_estudo GROUP BY materia").fetchall()
    ultima_sessao = {r[0]: r[1] for r in sessoes}

    cal_atividades = conn.execute("""
        SELECT materia, MAX(data) as ultima FROM calendario_atividades
        WHERE concluida = 1 AND materia != '' GROUP BY materia
    """).fetchall()
    ultima_cal = {r[0]: r[1] for r in cal_atividades}

    negligenciadas = []
    for r in materias:
        materia, pendentes = r[0], r[1]
        ultima_estudo = ultima_sessao.get(materia)
        ultima_ativ = ultima_cal.get(materia)

        if ultima_estudo and ultima_ativ:
            ultima = max(ultima_estudo, ultima_ativ)
        elif ultima_estudo:
            ultima = ultima_estudo
        elif ultima_ativ:
            ultima = ultima_ativ
        else:
            ultima = None

        dias_sem = (hoje - date.fromisoformat(ultima)).days if ultima else 999

        if dias_sem >= dias_limite:
            perf = conn.execute("""
                SELECT COUNT(*) as total, SUM(qr.acertou) as acertos
                FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
                WHERE q.materia = ?
            """, (materia,)).fetchone()
            pct_acerto = round((perf[1] or 0) / perf[0] * 100, 1) if perf[0] and perf[0] > 0 else 0

            negligenciadas.append({
                "materia": materia, "dias_sem_estudar": dias_sem,
                "topicos_pendentes": pendentes, "pct_acerto": pct_acerto,
                "urgencia": "alta" if dias_sem > 10 or (dias_sem > 5 and pct_acerto < 60) else "media",
                "sugestao": f"Estudar {min(3, pendentes)} tópicos + resolver {max(5, 10 - pct_acerto // 10)} questões"
            })

    negligenciadas.sort(key=lambda x: (-1 if x["urgencia"] == "alta" else 0, -x["dias_sem_estudar"]))
    return {"negligenciadas": negligenciadas, "total": len(negligenciadas), "dias_limite": dias_limite}


# ============================================================
# MICRO-REVISÕES
# ============================================================

@router.get("/api/micro-revisao")
def get_micro_revisao(quantidade: int = 5, conn=Depends(get_db_session)):
    """Gera sessão ultra-curta de micro-revisão."""
    items = []
    flashcards = conn.execute(
        "SELECT id, pergunta, resposta, materia FROM flashcards ORDER BY RANDOM() LIMIT ?", (quantidade,)
    ).fetchall()
    for f in flashcards:
        items.append({"tipo": "flashcard", "id": f[0], "pergunta": f[1], "resposta": f[2], "materia": f[3] or "Geral"})

    if len(items) < quantidade:
        falta = quantidade - len(items)
        topicos = conn.execute(
            "SELECT id, materia, topico FROM edital WHERE status != 'Concluído' ORDER BY RANDOM() LIMIT ?", (falta,)
        ).fetchall()
        for t in topicos:
            items.append({"tipo": "topico", "id": t[0], "pergunta": f"O que você sabe sobre: {t[2]}?",
                          "resposta": f"Tópico de {t[1]} — revise seu material.", "materia": t[1]})

    random.shuffle(items)
    return {"items": items[:quantidade], "total": len(items), "tempo_estimado_seg": quantidade * 24}


# ============================================================
# QUESTÕES DISSERTATIVAS
# ============================================================

@router.get("/api/questao-dissertativa")
def get_questao_dissertativa(materia: str = "", conn=Depends(get_db_session)):
    query = "SELECT id, materia, topico FROM edital WHERE status != 'Concluído'"
    params = []
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    query += " ORDER BY RANDOM() LIMIT 1"
    row = conn.execute(query, params).fetchone()

    if not row:
        return {"pergunta": None, "message": "Nenhum tópico disponível."}

    topico, materia_nome, edital_id = row[2], row[1], row[0]
    perguntas_modelo = [
        f"Explique com suas palavras o conceito de '{topico}' em {materia_nome}.",
        f"Quais são os principais aspectos de '{topico}'? Descreva pelo menos 3 pontos.",
        f"Como '{topico}' se relaciona com outros temas de {materia_nome}?",
        f"Dê um exemplo prático de aplicação de '{topico}' em uma prova de concurso.",
        f"Compare e diferencie os elementos principais de '{topico}'.",
    ]
    pergunta = random.choice(perguntas_modelo)
    return {"edital_id": edital_id, "materia": materia_nome, "topico": topico, "pergunta": pergunta,
            "dica": "Escreva sua resposta completa. Quanto mais detalhes, melhor a fixação."}


@router.post("/api/questao-dissertativa/salvar")
def salvar_questao_dissertativa(body: dict = Body(...), conn=Depends(get_db_session)):
    edital_id = body.get("edital_id")
    resposta = body.get("resposta", "")
    confianca = body.get("confianca", 3)

    if not resposta or not edital_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Preencha a resposta.")

    conn.execute("INSERT INTO resumos (edital_id, resumo, tipo, created_at) VALUES (?, ?, 'dissertativa', ?)",
                 (edital_id, resposta, today_str()))
    conn.execute("""
        INSERT INTO calendario_atividades (data, dia_semana, materia, tipo, tempo_min, concluida, concluida_at)
        VALUES (?, ?, ?, 'dissertativa', 5, 1, ?)
    """, (today_str(), date.today().weekday(), body.get("materia", ""), datetime.now().isoformat()))
    conn.commit()
    return {"ok": True, "confianca": confianca}


# ============================================================
# AUTOAVALIAÇÃO
# ============================================================

@router.get("/api/autoavaliacao")
def get_autoavaliacao(quantidade: int = 5, conn=Depends(get_db_session)):
    flashcards = conn.execute(
        "SELECT id, pergunta, resposta, materia FROM flashcards ORDER BY RANDOM() LIMIT ?", (quantidade,)
    ).fetchall()
    items = [{"id": f[0], "pergunta": f[1], "resposta": f[2], "materia": f[3] or "Geral"} for f in flashcards]
    return {"items": items, "instrucao": "Antes de revelar a resposta, indique sua confiança: 1=Não sei, 2=Acho que sei, 3=Tenho certeza"}


@router.post("/api/autoavaliacao/registrar")
def registrar_autoavaliacao(body: dict = Body(...), conn=Depends(get_db_session)):
    resultados = body.get("resultados", [])
    calibrados, superconfiante, subconfiante = 0, 0, 0

    for r in resultados:
        conf = r.get("confianca_pre", 2)
        acertou = r.get("acertou", False)
        fid = r.get("flashcard_id")
        if conf == 3 and not acertou:
            superconfiante += 1
        elif conf == 1 and acertou:
            subconfiante += 1
        elif (conf >= 2 and acertou) or (conf == 1 and not acertou):
            calibrados += 1
        if fid and not acertou:
            conn.execute("UPDATE flashcards SET proxima_revisao = ?, intervalo_dias = 1 WHERE id = ?", (today_str(), fid))

    conn.commit()
    total = len(resultados)
    calibracao_pct = round(calibrados / total * 100) if total > 0 else 0

    return {
        "ok": True, "total": total, "calibrados": calibrados,
        "superconfiante": superconfiante, "subconfiante": subconfiante,
        "calibracao_pct": calibracao_pct,
        "feedback": (
            "🎯 Excelente calibração! Você sabe o que sabe." if calibracao_pct >= 80
            else "⚠️ Cuidado com overconfidence — revise os temas que errou." if superconfiante > subconfiante
            else "💪 Você sabe mais do que pensa! Confie mais no seu conhecimento." if subconfiante > superconfiante
            else "📊 Continue praticando para melhorar sua metacognição."
        )
    }


# ============================================================
# SPACING INDICATOR
# ============================================================

@router.get("/api/spacing-indicator")
def get_spacing_indicator(conn=Depends(get_db_session)):
    materias = conn.execute("""
        SELECT materia, COUNT(*) as sessoes, MIN(data) as primeira, MAX(data) as ultima
        FROM sessoes_estudo WHERE data >= date('now', '-30 days')
        GROUP BY materia HAVING sessoes >= 2
    """).fetchall()

    resultado = []
    for r in materias:
        materia, sessoes, primeira, ultima = r[0], r[1], r[2], r[3]
        if primeira and ultima and primeira != ultima:
            dias_span = (date.fromisoformat(ultima) - date.fromisoformat(primeira)).days
            intervalo_medio = dias_span / (sessoes - 1) if sessoes > 1 else 0
            if 2 <= intervalo_medio <= 4:
                status, cor = "ideal", "#a6e3a1"
            elif intervalo_medio < 2:
                status, cor = "muito_junto", "#f9e2af"
            else:
                status, cor = "muito_espaco", "#f38ba8"

            resultado.append({
                "materia": materia, "sessoes_30d": sessoes,
                "intervalo_medio_dias": round(intervalo_medio, 1), "status": status, "cor": cor,
                "sugestao": (
                    "✅ Espaçamento ideal! Continue assim." if status == "ideal"
                    else "⚠️ Sessões muito juntas — espalhe mais ao longo da semana." if status == "muito_junto"
                    else "🔴 Intervalo muito grande — aumente a frequência."
                )
            })

    resultado.sort(key=lambda x: 0 if x["status"] == "ideal" else (1 if x["status"] == "muito_junto" else 2))
    return {"materias": resultado, "total": len(resultado)}

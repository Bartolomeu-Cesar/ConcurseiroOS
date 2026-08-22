"""Router do Calendário Personalizado e Atividades."""
import random
from datetime import date, datetime, timedelta
from typing import List

from fastapi import APIRouter, Body, Depends, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from models import CalendarioItem
from utils import today_str

router = APIRouter(prefix="", tags=["Calendário"])

NOMES_DIAS = ["Segunda", "Terça", "Quarta", "Quinta", "Sexta", "Sábado", "Domingo"]


# ============================================================
# CALENDÁRIO PERSONALIZADO
# ============================================================

@router.get("/api/calendario-personalizado")
def get_calendario_personalizado(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna o calendário personalizado salvo pelo usuário."""
    rows = conn.execute(
        "SELECT id, dia_semana, materia, topicos, tempo_min, tipo, ordem FROM calendario_personalizado WHERE user_id = ? ORDER BY dia_semana, ordem",
        (user_id,)
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
def add_calendario_item(body: CalendarioItem, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.dia_semana, body.materia, body.topicos, body.tempo_min, body.tipo, body.ordem, user_id)
    )
    conn.commit()
    return {"ok": True, "id": cur.lastrowid}


@router.delete("/api/calendario-personalizado/{id}")
def delete_calendario_item(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM calendario_personalizado WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


@router.delete("/api/calendario-personalizado")
def clear_calendario_personalizado(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM calendario_personalizado WHERE user_id = ?", (user_id,))
    conn.commit()
    return {"ok": True}


@router.post("/api/calendario-personalizado/salvar-completo")
def salvar_calendario_completo(dias: list = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Salva o calendário completo (limpa e recria)."""
    conn.execute("DELETE FROM calendario_personalizado WHERE user_id = ?", (user_id,))
    count = 0
    for item in dias:
        conn.execute(
            "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (item.get("dia_semana", 0), item.get("materia", ""), item.get("topicos", ""),
             item.get("tempo_min", 60), item.get("tipo", "estudo"), item.get("ordem", count), user_id)
        )
        count += 1
    conn.commit()
    return {"ok": True, "salvos": count}


# ============================================================
# ATIVIDADES DO CALENDÁRIO - CONCLUSÃO + STREAK
# ============================================================

@router.post("/api/calendario/atividade-concluida")
def marcar_atividade_concluida(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Marca uma atividade do calendário como concluída."""
    data_str = body.get("data", today_str())
    dia_semana = body.get("dia_semana", 0)
    materia = body.get("materia", "")
    tipo = body.get("tipo", "estudo")
    tempo_min = body.get("tempo_min", 0)

    conn.execute("""
        INSERT INTO calendario_atividades (data, dia_semana, materia, tipo, tempo_min, concluida, concluida_at, user_id)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    """, (data_str, dia_semana, materia, tipo, tempo_min, datetime.now().isoformat(), user_id))

    _update_calendario_streak(conn, data_str, body.get("total_atividades", 0), user_id)
    conn.commit()
    log.info(f"Atividade concluída: {materia} ({tipo}) em {data_str}")
    return {"ok": True}


@router.delete("/api/calendario/atividade-concluida")
def desmarcar_atividade_concluida(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Desmarca uma atividade (desfaz conclusão)."""
    data_str = body.get("data", today_str())
    materia = body.get("materia", "")
    tipo = body.get("tipo", "estudo")

    conn.execute("""
        DELETE FROM calendario_atividades
        WHERE data = ? AND materia = ? AND tipo = ? AND user_id = ?
        ORDER BY id DESC LIMIT 1
    """, (data_str, materia, tipo, user_id))

    _update_calendario_streak(conn, data_str, body.get("total_atividades", 0), user_id)
    conn.commit()
    return {"ok": True}


@router.get("/api/calendario/concluidas")
def get_atividades_concluidas(data: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna atividades concluídas de um dia (ou hoje)."""
    data_str = data or today_str()
    rows = conn.execute(
        "SELECT * FROM calendario_atividades WHERE data = ? AND concluida = 1 AND user_id = ?", (data_str, user_id)
    ).fetchall()
    return [dict(r) for r in rows]


@router.get("/api/calendario/streak")
def get_calendario_streak(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna streak de dias com 100% do calendário concluído."""
    rows = conn.execute("""
        SELECT data, pct_conclusao FROM calendario_streaks
        WHERE pct_conclusao >= 100 AND user_id = ? ORDER BY data DESC
    """, (user_id,)).fetchall()

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

    hoje_row = conn.execute("SELECT * FROM calendario_streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    return {
        "streak_calendario": streak,
        "melhor_streak_calendario": best,
        "hoje": dict(hoje_row) if hoje_row else {"total_atividades": 0, "concluidas": 0, "pct_conclusao": 0}
    }


def _update_calendario_streak(conn, data_str: str, total_atividades: int = 0, user_id: int = 0):
    """Atualiza o registro de streak do calendário para uma data."""
    concluidas = conn.execute(
        "SELECT COUNT(*) FROM calendario_atividades WHERE data = ? AND concluida = 1 AND user_id = ?", (data_str, user_id)
    ).fetchone()[0]
    pct = round((concluidas / total_atividades * 100) if total_atividades > 0 else 0, 1)
    xp = 50 if pct >= 100 else 0

    conn.execute("""
        INSERT INTO calendario_streaks (data, total_atividades, concluidas, pct_conclusao, xp_bonus, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(data) DO UPDATE SET
            total_atividades = ?, concluidas = ?, pct_conclusao = ?, xp_bonus = ?
    """, (data_str, total_atividades, concluidas, pct, xp, user_id,
          total_atividades, concluidas, pct, xp))


# ============================================================
# ALERTA DE MATÉRIAS NEGLIGENCIADAS
# ============================================================

@router.get("/api/calendario/materias-negligenciadas")
def get_materias_negligenciadas(dias_limite: int = 5, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna matérias importantes que não foram estudadas há mais de X dias."""
    hoje = date.today()
    materias = conn.execute("""
        SELECT materia, COUNT(*) as pendentes FROM edital
        WHERE status != 'Concluído' AND user_id = ? GROUP BY materia HAVING pendentes > 3 ORDER BY pendentes DESC
    """, (user_id,)).fetchall()

    sessoes = conn.execute("SELECT materia, MAX(data) as ultima FROM sessoes_estudo WHERE user_id = ? GROUP BY materia", (user_id,)).fetchall()
    ultima_sessao = {r[0]: r[1] for r in sessoes}

    cal_atividades = conn.execute("""
        SELECT materia, MAX(data) as ultima FROM calendario_atividades
        WHERE concluida = 1 AND materia != '' AND user_id = ? GROUP BY materia
    """, (user_id,)).fetchall()
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
                WHERE q.materia = ? AND qr.user_id = ?
            """, (materia, user_id)).fetchone()
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
def get_micro_revisao(quantidade: int = 5, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera sessão ultra-curta de micro-revisão."""
    items = []
    flashcards = conn.execute(
        "SELECT id, pergunta, resposta, materia FROM flashcards WHERE user_id = ? ORDER BY RANDOM() LIMIT ?", (user_id, quantidade)
    ).fetchall()
    for f in flashcards:
        items.append({"tipo": "flashcard", "id": f[0], "pergunta": f[1], "resposta": f[2], "materia": f[3] or "Geral"})

    if len(items) < quantidade:
        falta = quantidade - len(items)
        topicos = conn.execute(
            "SELECT id, materia, topico FROM edital WHERE status != 'Concluído' AND user_id = ? ORDER BY RANDOM() LIMIT ?", (user_id, falta)
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
def get_questao_dissertativa(materia: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    query = "SELECT id, materia, topico FROM edital WHERE status != 'Concluído' AND user_id = ?"
    params = [user_id]
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
def salvar_questao_dissertativa(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    edital_id = body.get("edital_id")
    resposta = body.get("resposta", "")
    confianca = body.get("confianca", 3)

    if not resposta or not edital_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Preencha a resposta.")

    conn.execute("INSERT INTO resumos (edital_id, resumo, tipo, created_at, user_id) VALUES (?, ?, 'dissertativa', ?, ?)",
                 (edital_id, resposta, today_str(), user_id))
    conn.execute("""
        INSERT INTO calendario_atividades (data, dia_semana, materia, tipo, tempo_min, concluida, concluida_at, user_id)
        VALUES (?, ?, ?, 'dissertativa', 5, 1, ?, ?)
    """, (today_str(), date.today().weekday(), body.get("materia", ""), datetime.now().isoformat(), user_id))
    conn.commit()
    return {"ok": True, "confianca": confianca}


# ============================================================
# AUTOAVALIAÇÃO
# ============================================================

@router.get("/api/autoavaliacao")
def get_autoavaliacao(quantidade: int = 5, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    flashcards = conn.execute(
        "SELECT id, pergunta, resposta, materia FROM flashcards WHERE user_id = ? ORDER BY RANDOM() LIMIT ?", (user_id, quantidade)
    ).fetchall()
    items = [{"id": f[0], "pergunta": f[1], "resposta": f[2], "materia": f[3] or "Geral"} for f in flashcards]
    return {"items": items, "instrucao": "Antes de revelar a resposta, indique sua confiança: 1=Não sei, 2=Acho que sei, 3=Tenho certeza"}


@router.post("/api/autoavaliacao/registrar")
def registrar_autoavaliacao(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
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
            conn.execute("UPDATE flashcards SET proxima_revisao = ?, intervalo_dias = 1 WHERE id = ? AND user_id = ?", (today_str(), fid, user_id))

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
def get_spacing_indicator(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    materias = conn.execute("""
        SELECT materia, COUNT(*) as sessoes, MIN(data) as primeira, MAX(data) as ultima
        FROM sessoes_estudo WHERE data >= date('now', '-30 days') AND user_id = ?
        GROUP BY materia HAVING sessoes >= 2
    """, (user_id,)).fetchall()

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


# ============================================================
# O QUE ESTUDAR AGORA — Sugestão baseada no horário + calendário
# ============================================================

@router.get("/api/calendario/agora", summary="O que estudar agora",
            description="Sugere atividade baseada no dia/hora atual + calendário planejado")
def o_que_estudar_agora(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna a atividade ideal para este momento baseado no calendário planejado."""
    agora = datetime.now()
    hora = agora.hour
    dia_semana = agora.weekday()  # 0=Monday

    # Determinar turno
    if 5 <= hora < 12:
        turno = "manha"
        turno_label = "☀️ Manhã"
    elif 12 <= hora < 18:
        turno = "tarde"
        turno_label = "🌤️ Tarde"
    elif 18 <= hora < 23:
        turno = "noite"
        turno_label = "🌙 Noite"
    else:
        turno = "madrugada"
        turno_label = "🦉 Madrugada"

    # Buscar atividades planejadas para hoje
    atividades_hoje = conn.execute("""
        SELECT materia, topicos, tempo_min, tipo, ordem
        FROM calendario_personalizado
        WHERE dia_semana = ? AND user_id = ?
        ORDER BY ordem
    """, (dia_semana, user_id)).fetchall()

    # Se não tem calendário personalizado, buscar do ciclo/edital
    if not atividades_hoje:
        # Fallback: matéria com menor acerto ou mais tempo sem estudar
        fraca = conn.execute("""
            SELECT q.materia, COUNT(*) as total,
                   ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct
            FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? GROUP BY q.materia HAVING total >= 3
            ORDER BY pct ASC LIMIT 1
        """, (user_id,)).fetchone()

        materia_sugerida = fraca["materia"] if fraca else "Revisão Geral"
        motivo = f"Menor acerto ({fraca['pct']}%)" if fraca else "Comece com revisões pendentes"

        return {
            "turno": turno,
            "turno_label": turno_label,
            "hora_atual": f"{hora:02d}:{agora.minute:02d}",
            "sugestao": {
                "materia": materia_sugerida,
                "tipo": "questoes" if fraca and fraca["pct"] < 60 else "estudo",
                "tempo_min": 30,
                "motivo": motivo,
            },
            "fonte": "inteligente",
            "atividades_planejadas": [],
        }

    # Distribuir atividades em turnos (proporcional)
    total_ativs = len(atividades_hoje)
    por_turno = max(1, total_ativs // 3)
    turnos_map = {"manha": [], "tarde": [], "noite": []}
    for i, a in enumerate(atividades_hoje):
        if i < por_turno:
            turnos_map["manha"].append(dict(a))
        elif i < por_turno * 2:
            turnos_map["tarde"].append(dict(a))
        else:
            turnos_map["noite"].append(dict(a))

    ativs_turno = turnos_map.get(turno, [])

    # Verificar quais já foram concluídas hoje
    concluidas = conn.execute("""
        SELECT materia, tipo FROM calendario_atividades
        WHERE data = ? AND concluida = 1 AND user_id = ?
    """, (today_str(), user_id)).fetchall()
    concluidas_set = set(f"{r['materia']}|{r['tipo']}" for r in concluidas)

    # Encontrar próxima atividade não concluída
    sugestao = None
    for a in ativs_turno:
        key = f"{a['materia']}|{a['tipo']}"
        if key not in concluidas_set:
            sugestao = {
                "materia": a["materia"],
                "tipo": a["tipo"],
                "tempo_min": a["tempo_min"],
                "topicos": a["topicos"],
                "motivo": f"Planejado para {turno_label.split(' ')[1]} de hoje",
            }
            break

    # Se todas do turno foram concluídas, buscar próximo turno
    if not sugestao:
        proximos_turnos = {"manha": "tarde", "tarde": "noite", "noite": "manha"}
        proximo = proximos_turnos.get(turno, "manha")
        for a in turnos_map.get(proximo, []):
            key = f"{a['materia']}|{a['tipo']}"
            if key not in concluidas_set:
                sugestao = {
                    "materia": a["materia"],
                    "tipo": a["tipo"],
                    "tempo_min": a["tempo_min"],
                    "topicos": a["topicos"],
                    "motivo": f"Adiantando atividade do próximo turno",
                }
                break

    # Se tudo concluído hoje
    if not sugestao:
        # Revisões SRS pendentes?
        pending_fc = conn.execute(
            "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?",
            (today_str(), user_id)
        ).fetchone()[0]
        if pending_fc > 0:
            sugestao = {
                "materia": "Flashcards",
                "tipo": "revisao",
                "tempo_min": min(15, pending_fc * 2),
                "topicos": "",
                "motivo": f"🎉 Calendário completo! {pending_fc} flashcards pendentes.",
            }
        else:
            sugestao = {
                "materia": "Descanso merecido",
                "tipo": "pausa",
                "tempo_min": 0,
                "motivo": "🏆 Todas as atividades do dia concluídas!",
            }

    # Progresso do dia
    total_planejado = len(atividades_hoje)
    total_concluido = len([a for a in atividades_hoje if f"{a['materia']}|{a['tipo']}" in concluidas_set])
    pct_dia = round(total_concluido / total_planejado * 100) if total_planejado > 0 else 0

    return {
        "turno": turno,
        "turno_label": turno_label,
        "hora_atual": f"{hora:02d}:{agora.minute:02d}",
        "sugestao": sugestao,
        "fonte": "calendario",
        "progresso_dia": {
            "concluidas": total_concluido,
            "total": total_planejado,
            "pct": pct_dia,
        },
        "atividades_planejadas": [dict(a) for a in ativs_turno],
    }


# ============================================================
# RESUMO SEMANAL DO CALENDÁRIO — progresso por dia
# ============================================================

@router.get("/api/calendario/progresso-semanal", summary="Progresso semanal do calendário")
def progresso_semanal_calendario(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna progresso de conclusão de atividades por dia da semana atual."""
    hoje = date.today()
    inicio_semana = (hoje - timedelta(days=hoje.weekday())).isoformat()
    fim_semana = (hoje - timedelta(days=hoje.weekday()) + timedelta(days=6)).isoformat()

    # Atividades planejadas por dia
    planejado = conn.execute("""
        SELECT dia_semana, COUNT(*) as total
        FROM calendario_personalizado WHERE user_id = ?
        GROUP BY dia_semana
    """, (user_id,)).fetchall()
    planejado_map = {r["dia_semana"]: r["total"] for r in planejado}

    # Atividades concluídas nesta semana
    concluidas = conn.execute("""
        SELECT data, COUNT(*) as concluidas
        FROM calendario_atividades
        WHERE data >= ? AND data <= ? AND concluida = 1 AND user_id = ?
        GROUP BY data
    """, (inicio_semana, fim_semana, user_id)).fetchall()
    concluidas_map = {r["data"]: r["concluidas"] for r in concluidas}

    dias = []
    total_planejado = 0
    total_concluido = 0
    nomes = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]

    for i in range(7):
        data_dia = (hoje - timedelta(days=hoje.weekday()) + timedelta(days=i)).isoformat()
        plan = planejado_map.get(i, 0)
        done = concluidas_map.get(data_dia, 0)
        pct = round(done / plan * 100) if plan > 0 else 0
        total_planejado += plan
        total_concluido += done

        is_today = data_dia == hoje.isoformat()
        is_past = data_dia < hoje.isoformat()

        dias.append({
            "dia_semana": i,
            "nome": nomes[i],
            "data": data_dia,
            "planejado": plan,
            "concluido": done,
            "pct": min(100, pct),
            "status": "completo" if pct >= 100 else "parcial" if done > 0 else ("pendente" if is_today or not is_past else "perdido"),
            "is_today": is_today,
        })

    pct_semanal = round(total_concluido / total_planejado * 100) if total_planejado > 0 else 0

    return {
        "dias": dias,
        "resumo": {
            "total_planejado": total_planejado,
            "total_concluido": total_concluido,
            "pct_semanal": pct_semanal,
        },
        "semana_inicio": inicio_semana,
        "semana_fim": fim_semana,
    }


# ============================================================
# RESET INTELIGENTE — Regenera calendário com todas as inteligências
# ============================================================

@router.post("/api/planejador/reset-inteligente", summary="Reset inteligente do calendário",
             description="Apaga calendário personalizado e gera novo otimizado usando todas as fontes de inteligência")
def reset_inteligente(body: dict = Body(default={}), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera calendário semanal otimizado usando TODAS as inteligências disponíveis."""
    from routers.treinador.analise import (
        _analyze_error_patterns,
        _get_banca_weights,
        _get_last_session_by_subject,
        _get_pending_reviews,
        _get_performance_by_subject,
    )

    edital_nome = body.get("edital_nome", "")
    cargo = body.get("cargo", "")

    # Get horas_dia from body > metas_config > default 4
    horas_dia = body.get("horas_dia")
    if not horas_dia:
        cfg = conn.execute("SELECT meta_horas FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
        horas_dia = cfg[0] if cfg and cfg[0] else 4.0
    horas_dia = float(horas_dia)
    tempo_dia_min = int(horas_dia * 60)

    # ===== 1. Gather ALL intelligence sources =====

    # Ciclo de estudos (matérias ativas com horas planejadas)
    ciclo = conn.execute(
        "SELECT materia, horas_alvo FROM ciclo_estudos WHERE ativo = 1 AND user_id = ? ORDER BY ordem", (user_id,)
    ).fetchall()
    ciclo_map = {r["materia"]: r["horas_alvo"] for r in ciclo}

    # Performance by subject
    desempenho = _get_performance_by_subject(conn, user_id)

    # Banca weights
    banca_weights = _get_banca_weights(conn, user_id, edital_nome, cargo)

    # Error patterns (caderno de erros)
    error_patterns = _analyze_error_patterns(conn, user_id, limit=20)
    error_rate_map = {}
    for ep in error_patterns:
        mat = ep["materia"]
        if mat not in error_rate_map:
            error_rate_map[mat] = ep["pct_erro"]
        else:
            error_rate_map[mat] = max(error_rate_map[mat], ep["pct_erro"])

    # Pending reviews (flashcards + tópicos)
    pending = _get_pending_reviews(conn, user_id)

    # Days since last study per subject
    ultima_sessao = _get_last_session_by_subject(conn, user_id)
    hoje = date.today()

    # Edital topics pending per subject
    query_edital = "SELECT materia, COUNT(*) as pendentes FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?"
    params_edital = [user_id]
    if edital_nome:
        query_edital += " AND edital_nome = ?"
        params_edital.append(edital_nome)
    if cargo:
        query_edital += " AND cargo = ?"
        params_edital.append(cargo)
    query_edital += " GROUP BY materia"
    topicos_pendentes_map = {r[0]: r[1] for r in conn.execute(query_edital, params_edital).fetchall()}

    # Flashcards due per subject
    review_due_map = {}
    try:
        fc_due = conn.execute("""
            SELECT materia, COUNT(*) as due FROM flashcards
            WHERE proxima_revisao <= ? AND user_id = ? AND materia != ''
            GROUP BY materia
        """, (today_str(), user_id)).fetchall()
        review_due_map = {r[0]: r[1] for r in fc_due}
    except Exception:
        pass

    # ===== 2. Filter to ONLY matérias from the active ciclo =====
    # The ciclo is the source of truth for what should be studied
    if ciclo_map:
        all_materias = set(ciclo_map.keys())
    else:
        # Fallback: if no ciclo, use edital topics (but warn)
        all_materias = set(topicos_pendentes_map.keys())
        if not all_materias:
            all_materias.update(desempenho.keys())

    if not all_materias:
        return {"ok": False, "message": "Nenhuma matéria encontrada. Importe um edital ou adicione matérias ao ciclo."}

    # ===== 3. Calculate weighted score per matéria =====
    # peso = (banca_weight * 0.3) + (error_rate * 0.25) + (days_neglected * 0.2) + (topics_pending * 0.15) + (review_due * 0.1)

    # Normalize helpers
    max_banca = max((bw.get("peso_pct", 0) for bw in banca_weights.values()), default=1) or 1
    max_topics = max(topicos_pendentes_map.values(), default=1) or 1
    max_reviews = max(review_due_map.values(), default=1) or 1

    scored_materias = []
    for mat in all_materias:
        # Banca weight (0-100 normalized)
        bw = banca_weights.get(mat, {}).get("peso_pct", 0)
        banca_norm = (bw / max_banca) * 100

        # Error rate (already 0-100)
        err_rate = error_rate_map.get(mat, 0)

        # Days neglected (cap at 30 → normalized to 100)
        ultima = ultima_sessao.get(mat)
        if ultima:
            try:
                dias_sem = (hoje - date.fromisoformat(ultima)).days
            except (ValueError, TypeError):
                dias_sem = 30
        else:
            dias_sem = 30
        days_norm = min(dias_sem, 30) / 30 * 100

        # Topics pending (normalized)
        topics_pend = topicos_pendentes_map.get(mat, 0)
        topics_norm = (topics_pend / max_topics) * 100

        # Reviews due (normalized)
        rev_due = review_due_map.get(mat, 0)
        review_norm = (rev_due / max_reviews) * 100

        peso = (banca_norm * 0.3) + (err_rate * 0.25) + (days_norm * 0.2) + (topics_norm * 0.15) + (review_norm * 0.1)

        # Boost: if performance is low, increase weight
        perf = desempenho.get(mat, {})
        if perf.get("total", 0) >= 5 and perf.get("pct", 100) < 50:
            peso *= 1.3
        elif perf.get("total", 0) >= 5 and perf.get("pct", 100) < 70:
            peso *= 1.1

        scored_materias.append({
            "materia": mat,
            "peso": round(peso, 2),
            "banca_pct": bw,
            "error_rate": err_rate,
            "dias_sem": dias_sem,
            "topics_pending": topics_pend,
            "review_due": rev_due,
            "pct_acerto": perf.get("pct", 0),
        })

    scored_materias.sort(key=lambda x: -x["peso"])

    # ===== 4. Distribute across 7 days =====
    total_peso = sum(m["peso"] for m in scored_materias) or 1

    # Determine frequency per matéria: top 30% → 3 days, middle 35% → 2 days, bottom 35% → 1 day
    total_mats = len(scored_materias)
    for i, m in enumerate(scored_materias):
        pos = i / max(total_mats, 1)
        m["freq"] = 3 if pos < 0.3 else 2 if pos < 0.65 else 1

    # Time allocation: 20% review/flashcards, 60% main study, 20% questions
    tempo_revisao = int(tempo_dia_min * 0.20)
    tempo_estudo = int(tempo_dia_min * 0.60)
    tempo_questoes = int(tempo_dia_min * 0.20)

    # Build pool of matérias for assignment
    pool = []
    for m in scored_materias:
        pool.extend([m] * m["freq"])

    dias_calendario = []
    last_day_materias = set()
    pool_idx = 0
    slots_por_dia = [3, 3, 3, 3, 3, 2, 0]  # Mon-Sat active, Sun rest/reduced

    for dia_idx in range(7):
        dia_atividades = []
        is_domingo = dia_idx == 6
        target_slots = slots_por_dia[dia_idx]

        # --- REVIEW BLOCK (20% of time) ---
        if not is_domingo:
            review_desc = ""
            if pending["flashcards"] > 0:
                review_desc = f"Revisar {pending['flashcards']} flashcards pendentes"
            elif pending["topicos"] > 0:
                review_desc = f"Revisar {pending['topicos']} tópicos com revisão espaçada"
            else:
                review_desc = "Revisão geral / Flashcards do dia"

            dia_atividades.append({
                "dia_semana": dia_idx,
                "materia": "Revisão",
                "topicos": review_desc,
                "tempo_min": tempo_revisao,
                "tipo": "revisao",
                "ordem": 0,
            })

        # --- MAIN STUDY BLOCK (60% of time, distributed by weight) ---
        if not is_domingo and target_slots > 0:
            used_today = set()
            assigned = []
            attempts = 0
            search_idx = pool_idx

            while len(assigned) < target_slots and attempts < len(pool) * 3 and pool:
                candidate = pool[search_idx % len(pool)]
                mat_name = candidate["materia"]
                if mat_name not in last_day_materias and mat_name not in used_today:
                    assigned.append(candidate)
                    used_today.add(mat_name)
                    pool_idx = (search_idx + 1) % len(pool)
                search_idx += 1
                attempts += 1

            # Fallback: if not enough assigned, allow repeats from top priorities
            if len(assigned) < target_slots:
                for m in scored_materias:
                    if m["materia"] not in used_today:
                        assigned.append(m)
                        used_today.add(m["materia"])
                        if len(assigned) >= target_slots:
                            break

            # Distribute study time proportionally by weight
            total_assigned_peso = sum(a["peso"] for a in assigned) or 1
            ordem = 1
            for a in assigned:
                proporcao = a["peso"] / total_assigned_peso
                tempo_mat_estudo = max(15, int(tempo_estudo * proporcao))

                # Get topics for this matéria
                topicos_query = "SELECT topico FROM edital WHERE materia = ? AND status != 'Concluído' AND arquivado = 0 AND user_id = ?"
                topicos_params = [a["materia"], user_id]
                if edital_nome:
                    topicos_query += " AND edital_nome = ?"
                    topicos_params.append(edital_nome)
                if cargo:
                    topicos_query += " AND cargo = ?"
                    topicos_params.append(cargo)
                topicos_query += " LIMIT 3"
                topicos_list = [r[0] for r in conn.execute(topicos_query, topicos_params).fetchall()]
                topicos_str = "; ".join(topicos_list) if topicos_list else "Revisão geral"

                dia_atividades.append({
                    "dia_semana": dia_idx,
                    "materia": a["materia"],
                    "topicos": topicos_str,
                    "tempo_min": tempo_mat_estudo,
                    "tipo": "estudo",
                    "ordem": ordem,
                })
                ordem += 1

            # --- QUESTIONS BLOCK (20% of time, weakest subjects) ---
            # Pick the weakest among assigned
            weakest = sorted(assigned, key=lambda x: x.get("pct_acerto", 0))[:2]
            if weakest:
                tempo_q_per = max(10, tempo_questoes // len(weakest))
                for w in weakest:
                    dia_atividades.append({
                        "dia_semana": dia_idx,
                        "materia": w["materia"],
                        "topicos": f"Questões de {w['materia']} (reforço)",
                        "tempo_min": tempo_q_per,
                        "tipo": "questoes",
                        "ordem": ordem,
                    })
                    ordem += 1

            last_day_materias = used_today
        else:
            # DOMINGO: reduced schedule - light review only
            dia_atividades.append({
                "dia_semana": dia_idx,
                "materia": "Revisão",
                "topicos": "Revisão leve / Descanso ativo (flashcards ou leitura)",
                "tempo_min": min(30, tempo_dia_min // 4),
                "tipo": "revisao",
                "ordem": 0,
            })
            if scored_materias:
                dia_atividades.append({
                    "dia_semana": dia_idx,
                    "materia": scored_materias[0]["materia"],
                    "topicos": "Revisão rápida da matéria prioritária",
                    "tempo_min": min(20, tempo_dia_min // 6),
                    "tipo": "revisao",
                    "ordem": 1,
                })

        dias_calendario.append(dia_atividades)

    # ===== 5. Delete old and save new calendario_personalizado =====
    conn.execute("DELETE FROM calendario_personalizado WHERE user_id = ?", (user_id,))

    count = 0
    for dia_atividades in dias_calendario:
        for ativ in dia_atividades:
            conn.execute(
                "INSERT INTO calendario_personalizado (dia_semana, materia, topicos, tempo_min, tipo, ordem, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (ativ["dia_semana"], ativ["materia"], ativ["topicos"], ativ["tempo_min"], ativ["tipo"], ativ["ordem"], user_id)
            )
            count += 1
    conn.commit()

    # ===== 6. Build response =====
    dias_response = []
    for dia_idx, dia_atividades in enumerate(dias_calendario):
        tempo_total = sum(a["tempo_min"] for a in dia_atividades)
        materias_dia = list(set(a["materia"] for a in dia_atividades if a["materia"] != "Revisão"))
        dias_response.append({
            "dia_semana": dia_idx,
            "nome": NOMES_DIAS[dia_idx],
            "atividades": dia_atividades,
            "tempo_total_min": tempo_total,
            "materias": materias_dia,
        })

    horas_semana = round(sum(d["tempo_total_min"] for d in dias_response) / 60, 1)
    total_materias_cal = len(set(m["materia"] for da in dias_calendario for m in da if m["materia"] != "Revisão"))

    log.info(f"Reset inteligente: {total_materias_cal} matérias, {horas_semana}h/semana, {count} atividades salvas")

    return {
        "ok": True,
        "message": f"Calendário regenerado com {total_materias_cal} matérias ({horas_semana}h/semana) usando análise inteligente.",
        "dias": dias_response,
        "stats": {
            "total_materias": total_materias_cal,
            "horas_semana": horas_semana,
            "horas_dia": horas_dia,
            "atividades_salvas": count,
            "distribuicao": [{"materia": m["materia"], "peso": m["peso"], "freq_semanal": m["freq"],
                              "banca_pct": m["banca_pct"], "pct_acerto": m["pct_acerto"],
                              "dias_sem_estudar": m["dias_sem"]} for m in scored_materias[:15]],
        },
    }

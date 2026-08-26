import random
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException

from constants import (
    LEVEL_XP,
    XP_PER_CORRECT,
    XP_PER_FLASHCARD,
    XP_PER_HOUR,
    XP_PER_QUESTION,
    XP_PER_SIMULADO,
    XP_PER_TOPIC,
    XP_STREAK_WEEKLY_BONUS,
)
from database import get_db_session
from deps import get_user_id
from schemas import DesafioCreate, MetasUpdate, StreakResponse
from services import get_horas_estudadas
from utils import calculate_streak, today_str

router = APIRouter(prefix="", tags=["Gamificação"])

# XP rewards are defined in constants.py

BADGES = [
    {"id": "first_hour", "name": "Primeira Hora", "desc": "Estudou 1 hora no total", "icon": "⏱", "condition": "horas >= 1"},
    {"id": "ten_hours", "name": "Maratonista", "desc": "Estudou 10 horas no total", "icon": "🏃", "condition": "horas >= 10"},
    {"id": "fifty_hours", "name": "Dedicado", "desc": "Estudou 50 horas no total", "icon": "💪", "condition": "horas >= 50"},
    {"id": "first_question", "name": "Primeira Questão", "desc": "Resolveu a primeira questão", "icon": "❓", "condition": "questoes >= 1"},
    {"id": "hundred_questions", "name": "Centurião", "desc": "Resolveu 100 questões", "icon": "💯", "condition": "questoes >= 100"},
    {"id": "five_hundred_questions", "name": "Mestre das Questões", "desc": "Resolveu 500 questões", "icon": "🎓", "condition": "questoes >= 500"},
    {"id": "streak_7", "name": "Semana Perfeita", "desc": "7 dias consecutivos de estudo", "icon": "🔥", "condition": "streak >= 7"},
    {"id": "streak_30", "name": "Mês de Ferro", "desc": "30 dias consecutivos de estudo", "icon": "⚡", "condition": "streak >= 30"},
    {"id": "first_simulado", "name": "Simulador", "desc": "Completou o primeiro simulado", "icon": "📝", "condition": "simulados >= 1"},
    {"id": "accuracy_80", "name": "Precisão Cirúrgica", "desc": "80%+ de acerto em questões", "icon": "🎯", "condition": "accuracy >= 80"},
    {"id": "ten_topics", "name": "Explorador", "desc": "Concluiu 10 tópicos do edital", "icon": "🗺", "condition": "topicos >= 10"},
    {"id": "fifty_topics", "name": "Conquistador", "desc": "Concluiu 50 tópicos do edital", "icon": "🏆", "condition": "topicos >= 50"},
    {"id": "all_flashcards", "name": "Memória de Elefante", "desc": "Revisou todos os flashcards do dia", "icon": "🧠", "condition": "flashcards_dia_ok"},
    {"id": "night_owl", "name": "Coruja Noturna", "desc": "Estudou após as 22h", "icon": "🦉", "condition": "special"},
    {"id": "early_bird", "name": "Madrugador", "desc": "Estudou antes das 6h", "icon": "🌅", "condition": "special"},
]


@router.get("/api/streaks", response_model=StreakResponse, summary="Streak e gamificação", description="Retorna streak atual, dados de hoje, XP e conquistas")
def get_streaks(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna streak atual (dias consecutivos) e dados de hoje"""
    # Dados de hoje
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    hoje_data = dict(hoje) if hoje else {"data": today_str(), "horas_estudadas": 0, "questoes_resolvidas": 0, "flashcards_revisados": 0}

    streak_info = calculate_streak(conn, user_id)

    return {
        "streak_atual": streak_info["streak_atual"],
        "melhor_streak": streak_info["melhor_streak"],
        "hoje": hoje_data
    }


@router.get("/api/metas")
def get_metas(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    config = conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()

    config_dict = dict(config) if config else {"meta_horas": 3.0, "meta_questoes": 30, "meta_flashcards": 10, "meta_paginas": 20, "meta_sumulas": 0}
    hoje_dict = dict(hoje) if hoje else {"horas_estudadas": 0, "questoes_resolvidas": 0, "flashcards_revisados": 0, "sumulas_revisadas": 0}

    # Usar sessoes_estudo como fonte de verdade para horas (evita dessincronização)
    horas_hoje = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data = ? AND user_id = ?", (today_str(), user_id)
    ).fetchone()[0]

    # Contar súmulas revisadas hoje
    sumulas_hoje = hoje_dict.get("sumulas_revisadas", 0)

    return {
        "config": config_dict,
        "progresso": {
            "horas": round(horas_hoje, 3),
            "questoes": hoje_dict.get("questoes_resolvidas", 0),
            "flashcards": hoje_dict.get("flashcards_revisados", 0),
            "sumulas": sumulas_hoje
        }
    }


@router.put("/api/metas")
def update_metas(body: MetasUpdate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    # Ensure row exists for this user
    existing = conn.execute("SELECT id FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    if existing:
        conn.execute("""
            UPDATE metas_config SET meta_horas = ?, meta_questoes = ?, meta_flashcards = ?, meta_paginas = ?, meta_sumulas = ?
            WHERE user_id = ?
        """, (body.meta_horas, body.meta_questoes, body.meta_flashcards, body.meta_paginas, body.meta_sumulas, user_id))
    else:
        conn.execute("""
            INSERT INTO metas_config (meta_horas, meta_questoes, meta_flashcards, meta_paginas, meta_sumulas, user_id)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (body.meta_horas, body.meta_questoes, body.meta_flashcards, body.meta_paginas, body.meta_sumulas, user_id))
    conn.commit()
    return {"ok": True}


@router.get("/api/gamification")
def get_gamification(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna XP, nível, badges e progresso do usuário"""
    # Calcular XP baseado nas atividades
    horas = get_horas_estudadas(conn, user_id)
    questoes_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]
    questoes_certas = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1 AND user_id = ?", (user_id,)).fetchone()[0]
    flashcards_rev = conn.execute("SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ?", (user_id,)).fetchone()[0]
    topicos_concluidos = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)).fetchone()[0]
    simulados_feitos = conn.execute("SELECT COUNT(*) FROM simulados WHERE status = 'finalizado' AND user_id = ?", (user_id,)).fetchone()[0]

    # Streak atual
    streak_info = calculate_streak(conn, user_id)
    streak = streak_info["streak_atual"]

    # Calcular XP
    xp = int(
        horas * XP_PER_HOUR +
        questoes_total * XP_PER_QUESTION +
        questoes_certas * XP_PER_CORRECT +
        flashcards_rev * XP_PER_FLASHCARD +
        topicos_concluidos * XP_PER_TOPIC +
        simulados_feitos * XP_PER_SIMULADO +
        (streak // 7) * XP_STREAK_WEEKLY_BONUS
    )

    nivel = (xp // LEVEL_XP) + 1
    xp_no_nivel = xp % LEVEL_XP
    xp_para_proximo = LEVEL_XP

    # Verificar badges
    accuracy = (questoes_certas / questoes_total * 100) if questoes_total > 0 else 0

    # Check time-based badges (Night Owl / Early Bird)
    has_night_session = conn.execute(
        "SELECT 1 FROM sessoes_estudo WHERE created_at != '' AND CAST(substr(created_at, 12, 2) AS INTEGER) >= 22 AND user_id = ? LIMIT 1",
        (user_id,)
    ).fetchone() is not None
    has_early_session = conn.execute(
        "SELECT 1 FROM sessoes_estudo WHERE created_at != '' AND CAST(substr(created_at, 12, 2) AS INTEGER) < 6 AND user_id = ? LIMIT 1",
        (user_id,)
    ).fetchone() is not None

    # Check flashcards_dia_ok (all due flashcards reviewed today)
    flashcards_pending_today = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)
    ).fetchone()[0]
    hoje_streak = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()
    flashcards_today_done = hoje_streak["flashcards_revisados"] if hoje_streak else 0
    flashcards_dia_ok = flashcards_pending_today == 0 and flashcards_today_done > 0

    badges_earned = []
    for badge in BADGES:
        earned = False
        cond = badge["condition"]
        if cond == "special":
            if badge["id"] == "night_owl":
                earned = has_night_session
            elif badge["id"] == "early_bird":
                earned = has_early_session
        elif cond == "flashcards_dia_ok":
            earned = flashcards_dia_ok
        elif (cond == "horas >= 1" and horas >= 1 or cond == "horas >= 10" and horas >= 10 or
              cond == "horas >= 50" and horas >= 50 or cond == "questoes >= 1" and questoes_total >= 1 or
              cond == "questoes >= 100" and questoes_total >= 100 or cond == "questoes >= 500" and questoes_total >= 500 or
              cond == "streak >= 7" and streak >= 7 or cond == "streak >= 30" and streak >= 30 or
              cond == "simulados >= 1" and simulados_feitos >= 1 or
              cond == "accuracy >= 80" and accuracy >= 80 and questoes_total >= 20 or
              cond == "topicos >= 10" and topicos_concluidos >= 10 or cond == "topicos >= 50" and topicos_concluidos >= 50):
            earned = True

        if earned:
            badges_earned.append(badge)

    return {
        "xp": xp,
        "nivel": nivel,
        "xp_no_nivel": xp_no_nivel,
        "xp_para_proximo": xp_para_proximo,
        "pct_nivel": round(xp_no_nivel / xp_para_proximo * 100),
        "badges_earned": badges_earned,
        "badges_total": len(BADGES),
        "stats": {
            "horas": round(horas, 1),
            "questoes": questoes_total,
            "acertos": questoes_certas,
            "accuracy": round(accuracy, 1),
            "streak": streak,
            "topicos": topicos_concluidos,
            "simulados": simulados_feitos,
            "flashcards": flashcards_rev
        }
    }


@router.get("/api/conquistas-diarias")
def conquistas_diarias(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Gera missões diárias baseadas no progresso"""
    # Buscar matérias do ciclo ativo (se houver)
    materias_ciclo = [r[0] for r in conn.execute(
        "SELECT materia FROM ciclo_estudos WHERE ativo = 1 AND user_id = ?", (user_id,)
    ).fetchall()]

    # Buscar matérias menos estudadas (filtrar pelo ciclo se ativo)
    if materias_ciclo:
        placeholders = ','.join('?' * len(materias_ciclo))
        mat_fraca = conn.execute(f"""
            SELECT materia FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?
            AND materia IN ({placeholders})
            GROUP BY materia ORDER BY SUM(horas_estudadas) ASC LIMIT 5
        """, (user_id, *materias_ciclo)).fetchall()
    else:
        mat_fraca = conn.execute("""
            SELECT materia FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?
            GROUP BY materia ORDER BY SUM(horas_estudadas) ASC LIMIT 5
        """, (user_id,)).fetchall()

    # Dados de hoje
    hoje = conn.execute("SELECT * FROM streaks WHERE data = ? AND user_id = ?", (today_str(), user_id)).fetchone()

    missoes = []
    materias_fracas = [r[0] for r in mat_fraca] if mat_fraca else ['Geral']
    mat = random.choice(materias_fracas)

    missoes.append({"titulo": f"Resolver 5 questões de {mat}", "tipo": "questoes", "meta": 5, "materia": mat, "xp": 50})
    missoes.append({"titulo": "Estudar 1 hora hoje", "tipo": "horas", "meta": 1, "materia": "", "xp": 100})
    missoes.append({"titulo": "Revisar todos os flashcards pendentes", "tipo": "flashcards", "meta": 0, "materia": "", "xp": 30})

    if hoje:
        missoes.append({"titulo": "Concluir 3 tópicos do edital", "tipo": "topicos", "meta": 3, "materia": "", "xp": 75})

    return missoes


@router.get("/api/desafios")
def list_desafios(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    rows = conn.execute("SELECT * FROM desafios WHERE user_id = ? ORDER BY finalizado ASC, created_at DESC", (user_id,)).fetchall()
    desafios = []
    for r in rows:
        d = dict(r)
        # Calcular dias restantes
        try:
            criado = date.fromisoformat(d["created_at"])
            expira = criado + timedelta(days=d["dias"])
            d["dias_restantes"] = max(0, (expira - date.today()).days)
            d["expirado"] = d["dias_restantes"] == 0 and not d["finalizado"]
        except:
            d["dias_restantes"] = d["dias"]
            d["expirado"] = False
        d["pct"] = min(100, round(d["progresso"] / d["meta_valor"] * 100, 1)) if d["meta_valor"] > 0 else 0
        desafios.append(d)
    return desafios


@router.post("/api/desafios")
def create_desafio(body: DesafioCreate, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    cur = conn.execute(
        "INSERT INTO desafios (titulo, meta_tipo, meta_valor, materia, dias, created_at, user_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (body.titulo, body.meta_tipo, body.meta_valor, body.materia, body.dias, today_str(), user_id))
    conn.commit()
    return {"id": cur.lastrowid, "ok": True}


@router.delete("/api/desafios/{id}")
def delete_desafio(id: int, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    conn.execute("DELETE FROM desafios WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    return {"ok": True}


@router.put("/api/desafios/{id}")
def update_desafio(id: int, body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Edita um desafio existente."""
    existing = conn.execute("SELECT * FROM desafios WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not existing:
        raise HTTPException(status_code=404, detail="Desafio não encontrado")

    titulo = body.get("titulo", existing["titulo"])
    meta_tipo = body.get("meta_tipo", existing["meta_tipo"])
    meta_valor = body.get("meta_valor", existing["meta_valor"])
    materia = body.get("materia", existing["materia"])
    dias = body.get("dias", existing["dias"])

    conn.execute(
        "UPDATE desafios SET titulo = ?, meta_tipo = ?, meta_valor = ?, materia = ?, dias = ? WHERE id = ? AND user_id = ?",
        (titulo, meta_tipo, meta_valor, materia, dias, id, user_id)
    )
    conn.commit()
    return {"ok": True, "id": id}


@router.post("/api/desafios/atualizar-progresso")
def atualizar_progresso_desafios(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Atualiza o progresso de TODOS os desafios ativos baseado nos dados reais."""
    desafios = conn.execute("SELECT * FROM desafios WHERE finalizado = 0 AND user_id = ?", (user_id,)).fetchall()
    atualizados = 0
    just_completed = []

    for d in desafios:
        criado = d["created_at"]
        meta_tipo = d["meta_tipo"]
        materia = d["materia"]
        meta_valor = d["meta_valor"]
        was_incomplete = d["progresso"] < meta_valor

        progresso = 0
        if meta_tipo == "questoes":
            if materia:
                progresso = conn.execute(
                    "SELECT COUNT(*) FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id WHERE qr.data >= ? AND q.materia = ? AND qr.user_id = ?",
                    (criado, materia, user_id)
                ).fetchone()[0]
            else:
                progresso = conn.execute(
                    "SELECT COUNT(*) FROM questoes_respostas WHERE data >= ? AND user_id = ?", (criado, user_id)
                ).fetchone()[0]
        elif meta_tipo == "horas":
            if materia:
                row = conn.execute(
                    "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND materia = ? AND user_id = ?",
                    (criado, materia, user_id)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND user_id = ?", (criado, user_id)
                ).fetchone()
            progresso = int(row[0])
        elif meta_tipo == "flashcards":
            progresso = conn.execute(
                "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE data >= ? AND user_id = ?", (criado, user_id)
            ).fetchone()[0]
        elif meta_tipo == "topicos":
            if materia:
                progresso = conn.execute(
                    "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND materia = ? AND user_id = ?", (materia, user_id)
                ).fetchone()[0]
            else:
                progresso = conn.execute(
                    "SELECT COUNT(*) FROM edital WHERE status = 'Concluído' AND user_id = ?", (user_id,)
                ).fetchone()[0]

        finalizado = 1 if progresso >= meta_valor else 0
        conn.execute(
            "UPDATE desafios SET progresso = ?, finalizado = ? WHERE id = ? AND user_id = ?",
            (min(progresso, meta_valor), finalizado, d["id"], user_id)
        )
        atualizados += 1

        # Track just-completed challenges for celebration
        if was_incomplete and finalizado:
            just_completed.append({
                "id": d["id"],
                "titulo": d["titulo"],
                "meta_tipo": meta_tipo,
                "meta_valor": meta_valor,
                "materia": materia or ""
            })

    conn.commit()
    return {"ok": True, "atualizados": atualizados, "just_completed": just_completed}


@router.get("/api/desafios/sugestoes")
def sugestoes_desafios(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Sugere desafios baseados no desempenho atual."""
    sugestoes = []

    # 1. Matéria mais fraca (< 60% acerto, mínimo 5 questões)
    fraca = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia HAVING total >= 5
        ORDER BY (CAST(acertos AS REAL) / total) ASC LIMIT 1
    """, (user_id,)).fetchone()
    if fraca:
        pct = round(fraca["acertos"] / fraca["total"] * 100)
        if pct < 70:
            sugestoes.append({
                "titulo": f"Dominar {fraca['materia']}",
                "descricao": f"Você está com {pct}% de acerto. Resolva 30 questões para melhorar!",
                "meta_tipo": "questoes",
                "meta_valor": 30,
                "materia": fraca["materia"],
                "dias": 7,
                "icon": "🎯"
            })

    # 2. Streak de estudo
    streak = conn.execute("SELECT COUNT(*) FROM streaks WHERE data >= ? AND user_id = ?",
        ((date.today() - timedelta(days=6)).isoformat(), user_id)).fetchone()[0]
    if streak < 5:
        sugestoes.append({
            "titulo": "Estudar 7 dias seguidos",
            "descricao": "Construa o hábito! Estude pelo menos 30min por dia.",
            "meta_tipo": "horas",
            "meta_valor": 4,
            "materia": "",
            "dias": 7,
            "icon": "🔥"
        })

    # 3. Flashcards
    pendentes = conn.execute(
        "SELECT COUNT(*) FROM flashcards WHERE proxima_revisao <= ? AND user_id = ?", (today_str(), user_id)
    ).fetchone()[0]
    if pendentes > 10:
        sugestoes.append({
            "titulo": f"Zerar {pendentes} revisões pendentes",
            "descricao": "Flashcards atrasados comprometem a memória de longo prazo.",
            "meta_tipo": "flashcards",
            "meta_valor": pendentes,
            "materia": "",
            "dias": 3,
            "icon": "🧠"
        })

    # 4. Concluir tópicos do edital
    pendentes_edital = conn.execute(
        "SELECT COUNT(*) FROM edital WHERE status != 'Concluído' AND arquivado = 0 AND user_id = ?", (user_id,)
    ).fetchone()[0]
    if pendentes_edital > 0:
        meta = min(10, pendentes_edital)
        sugestoes.append({
            "titulo": f"Concluir {meta} tópicos do edital",
            "descricao": "Avance no edital para cobrir mais conteúdo antes da prova.",
            "meta_tipo": "topicos",
            "meta_valor": meta,
            "materia": "",
            "dias": 7,
            "icon": "📋"
        })

    # 5. Volume de questões
    questoes_semana = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE data >= ? AND user_id = ?",
        ((date.today() - timedelta(days=6)).isoformat(), user_id)
    ).fetchone()[0]
    if questoes_semana < 50:
        sugestoes.append({
            "titulo": "Resolver 50 questões esta semana",
            "descricao": f"Você fez {questoes_semana} na última semana. Aumente o volume!",
            "meta_tipo": "questoes",
            "meta_valor": 50,
            "materia": "",
            "dias": 7,
            "icon": "❓"
        })

    # 6. Maratona de horas (estudar 10h na semana)
    horas_semana = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE data >= ? AND user_id = ?",
        ((date.today() - timedelta(days=6)).isoformat(), user_id)
    ).fetchone()[0]
    if horas_semana < 10:
        sugestoes.append({
            "titulo": "Maratona: 10 horas esta semana",
            "descricao": f"Você estudou {round(horas_semana, 1)}h na última semana. Aumente a consistência!",
            "meta_tipo": "horas",
            "meta_valor": 10,
            "materia": "",
            "dias": 7,
            "icon": "⏱"
        })

    # 7. Intercalar matérias (estudar pelo menos 4 matérias diferentes)
    materias_semana = conn.execute(
        "SELECT COUNT(DISTINCT materia) FROM sessoes_estudo WHERE data >= ? AND user_id = ?",
        ((date.today() - timedelta(days=6)).isoformat(), user_id)
    ).fetchone()[0]
    if materias_semana < 4:
        sugestoes.append({
            "titulo": "Interleaving: estudar 4+ matérias",
            "descricao": "Alternar matérias melhora retenção em 40% (Bjork, 2011). Diversifique!",
            "meta_tipo": "horas",
            "meta_valor": 4,
            "materia": "",
            "dias": 7,
            "icon": "🔀"
        })

    # 8. Caderno de erros — revisar erros antigos
    erros_pendentes = 0
    try:
        erros_pendentes = conn.execute(
            "SELECT COUNT(*) FROM erros_revisao WHERE user_id = ? AND proxima_revisao <= ?",
            (user_id, today_str())
        ).fetchone()[0]
    except Exception:
        pass
    if erros_pendentes >= 5:
        sugestoes.append({
            "titulo": f"Revisar {min(erros_pendentes, 20)} erros do caderno",
            "descricao": "Erros não revisados se consolidam. Retrieval practice dos erros é a chave!",
            "meta_tipo": "questoes",
            "meta_valor": min(erros_pendentes, 20),
            "materia": "",
            "dias": 5,
            "icon": "📕"
        })

    # 9. Simulado completo
    simulados_mes = conn.execute(
        "SELECT COUNT(*) FROM simulados WHERE status = 'finalizado' AND user_id = ? AND created_at >= ?",
        (user_id, (date.today() - timedelta(days=30)).isoformat())
    ).fetchone()[0]
    if simulados_mes < 2:
        sugestoes.append({
            "titulo": "Completar 1 simulado cronometrado",
            "descricao": "Simular a prova real treina gestão de tempo e controle emocional.",
            "meta_tipo": "questoes",
            "meta_valor": 40,
            "materia": "",
            "dias": 7,
            "icon": "📝"
        })

    # 10. Accuracy challenge — acertar 80%+ em uma matéria
    mat_perto = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(qr.acertou) as acertos
        FROM questoes_respostas qr JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ?
        GROUP BY q.materia HAVING total >= 5
        ORDER BY (CAST(acertos AS REAL) / total) DESC LIMIT 1
    """, (user_id, (date.today() - timedelta(days=14)).isoformat())).fetchone()
    if mat_perto:
        pct_atual = round(mat_perto["acertos"] / mat_perto["total"] * 100)
        if 60 <= pct_atual < 80:
            sugestoes.append({
                "titulo": f"Precisão 80% em {mat_perto['materia']}",
                "descricao": f"Você está com {pct_atual}%. Foque na qualidade, não só volume!",
                "meta_tipo": "questoes",
                "meta_valor": 20,
                "materia": mat_perto["materia"],
                "dias": 7,
                "icon": "🎯"
            })

    # 11. Streak challenge (manter por 5 dias)
    from utils import calculate_streak
    streak_info = calculate_streak(conn, user_id)
    if streak_info["streak_atual"] < 5:
        sugestoes.append({
            "titulo": "Manter streak por 5 dias",
            "descricao": f"Streak atual: {streak_info['streak_atual']}. Hábito vence motivação!",
            "meta_tipo": "horas",
            "meta_valor": 3,
            "materia": "",
            "dias": 5,
            "icon": "🔥"
        })

    # 12. Speed challenge — resolver questões rápido
    tempo_medio = conn.execute(
        "SELECT AVG(tempo_segundos) FROM questoes_respostas WHERE tempo_segundos > 0 AND user_id = ? AND data >= ?",
        (user_id, (date.today() - timedelta(days=7)).isoformat())
    ).fetchone()[0]
    if tempo_medio and tempo_medio > 120:
        sugestoes.append({
            "titulo": "Speed Run: 10 questões em 15 min",
            "descricao": f"Tempo médio atual: {int(tempo_medio)}s. Treinar velocidade sem perder precisão.",
            "meta_tipo": "questoes",
            "meta_valor": 10,
            "materia": "",
            "dias": 3,
            "icon": "⚡"
        })

    # Shuffle para variedade e retornar até 6 sugestões
    if len(sugestoes) > 6:
        # Manter os primeiros 2 (mais relevantes) + shuffle do resto
        fixos = sugestoes[:2]
        resto = sugestoes[2:]
        random.shuffle(resto)
        sugestoes = fixos + resto[:4]

    return sugestoes[:6]


# ============================================================
# STREAK FREEZE
# ============================================================

MAX_STREAK_FREEZES = 3
STREAK_FREEZE_EARN_INTERVAL = 7  # Ganha 1 freeze a cada 7 dias de streak


@router.get("/api/streak-freeze")
def get_streak_freeze(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna informações sobre streak freeze do usuário."""
    config = conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    freezes_available = config["streak_freezes_available"] if config and "streak_freezes_available" in config.keys() else 1
    freezes_used = config["streak_freezes_used"] if config and "streak_freezes_used" in config.keys() else 0

    streak_info = calculate_streak(conn, user_id)
    streak = streak_info["streak_atual"]

    # Check if user would earn a new freeze today
    can_earn = freezes_available < MAX_STREAK_FREEZES and streak > 0 and streak % STREAK_FREEZE_EARN_INTERVAL == 0

    return {
        "freezes_available": freezes_available,
        "freezes_used": freezes_used,
        "max_freezes": MAX_STREAK_FREEZES,
        "streak_atual": streak,
        "earn_next_at": ((streak // STREAK_FREEZE_EARN_INTERVAL) + 1) * STREAK_FREEZE_EARN_INTERVAL if not can_earn else streak,
        "can_earn_today": can_earn
    }


@router.post("/api/streak-freeze/use")
def use_streak_freeze(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Usa um streak freeze para proteger o streak de ontem. Deve ser chamado antes de o streak ser recalculado."""
    config = conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    freezes_available = config["streak_freezes_available"] if "streak_freezes_available" in config.keys() else 1
    if freezes_available <= 0:
        raise HTTPException(status_code=400, detail="Sem freezes disponíveis")

    # Check if yesterday had no activity (freeze would be needed)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    yesterday_data = conn.execute(
        "SELECT * FROM streaks WHERE data = ? AND user_id = ?", (yesterday, user_id)
    ).fetchone()

    had_activity = False
    if yesterday_data:
        had_activity = (
            yesterday_data["horas_estudadas"] > 0 or
            yesterday_data["questoes_resolvidas"] > 0 or
            yesterday_data["flashcards_revisados"] > 0
        )

    if had_activity:
        return {"ok": False, "message": "Ontem já teve atividade — freeze não necessário"}

    # Insert a minimal streak record for yesterday to preserve the streak
    if yesterday_data:
        # Mark as freeze day
        conn.execute(
            "UPDATE streaks SET horas_estudadas = 0.001 WHERE data = ? AND user_id = ?",
            (yesterday, user_id)
        )
    else:
        conn.execute(
            "INSERT INTO streaks (data, horas_estudadas, questoes_resolvidas, flashcards_revisados, user_id) VALUES (?, 0.001, 0, 0, ?)",
            (yesterday, user_id)
        )

    # Decrement freeze
    conn.execute(
        "UPDATE metas_config SET streak_freezes_available = streak_freezes_available - 1, streak_freezes_used = streak_freezes_used + 1 WHERE user_id = ?",
        (user_id,)
    )
    conn.commit()

    return {"ok": True, "message": "Streak freeze ativado! Seu streak está protegido.", "freezes_remaining": freezes_available - 1}


@router.post("/api/streak-freeze/earn")
def earn_streak_freeze(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Ganha um streak freeze por manter streak de 7+ dias. Chamado automaticamente."""
    config = conn.execute("SELECT * FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    if not config:
        raise HTTPException(status_code=404, detail="Configuração não encontrada")

    freezes_available = config["streak_freezes_available"] if "streak_freezes_available" in config.keys() else 1
    last_earned = config["last_freeze_earned"] if "last_freeze_earned" in config.keys() else ""

    if freezes_available >= MAX_STREAK_FREEZES:
        return {"ok": False, "message": f"Máximo de {MAX_STREAK_FREEZES} freezes atingido"}

    streak_info = calculate_streak(conn, user_id)
    streak = streak_info["streak_atual"]

    # Only earn if streak is a multiple of 7 and haven't earned today
    if streak < STREAK_FREEZE_EARN_INTERVAL or streak % STREAK_FREEZE_EARN_INTERVAL != 0:
        return {"ok": False, "message": f"Precisa de streak múltiplo de {STREAK_FREEZE_EARN_INTERVAL} dias"}

    if last_earned == today_str():
        return {"ok": False, "message": "Já ganhou um freeze hoje"}

    conn.execute(
        "UPDATE metas_config SET streak_freezes_available = streak_freezes_available + 1, last_freeze_earned = ? WHERE user_id = ?",
        (today_str(), user_id)
    )
    conn.commit()

    return {"ok": True, "message": "🧊 Streak Freeze ganho! Agora você pode perder 1 dia sem quebrar o streak.", "freezes_available": freezes_available + 1}


# ============================================================
# DESIRED RETENTION (FSRS Settings)
# ============================================================

@router.get("/api/settings/desired-retention", summary="Obter desired retention", tags=["FSRS"])
def get_desired_retention(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna o valor de desired_retention do usuário (padrão: 0.9)."""
    from constants import FSRS_DEFAULT_RETENTION

    desired_retention = FSRS_DEFAULT_RETENTION
    try:
        row = conn.execute(
            "SELECT desired_retention FROM metas_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row and row[0] is not None:
            desired_retention = row[0]
    except Exception:
        pass  # Column doesn't exist yet

    return {"desired_retention": desired_retention}


@router.put("/api/settings/desired-retention", summary="Atualizar desired retention", tags=["FSRS"])
def update_desired_retention(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Atualiza o desired_retention do usuário.
    Body: {"desired_retention": 0.9}
    Valor aceito: 0.7 a 0.99
    """
    desired_retention = body.get("desired_retention", 0.9)

    # Validate range
    if not isinstance(desired_retention, (int, float)):
        raise HTTPException(status_code=400, detail="desired_retention deve ser um número entre 0.7 e 0.99")
    if desired_retention < 0.7 or desired_retention > 0.99:
        raise HTTPException(status_code=400, detail="desired_retention deve estar entre 0.7 e 0.99")

    try:
        conn.execute(
            "UPDATE metas_config SET desired_retention = ? WHERE user_id = ?",
            (round(desired_retention, 4), user_id)
        )
        conn.commit()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao atualizar desired_retention: {str(e)}")

    return {"ok": True, "desired_retention": round(desired_retention, 4)}

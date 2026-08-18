import random
from datetime import date, timedelta

from fastapi import APIRouter

from database import get_db
from models import MetasUpdate, DesafioCreate
from utils import today_str, calculate_streak

router = APIRouter()

# XP rewards:
# - Estudar 1 hora = 100 XP
# - Resolver questão = 10 XP (acertar = +5 bonus)
# - Revisar flashcard = 5 XP
# - Completar tópico do edital = 25 XP
# - Completar simulado = 50 XP
# - Streak de 7 dias = 200 XP bonus

# Levels: cada 500 XP = 1 nível
LEVEL_XP = 500

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


@router.get("/api/streaks")
def get_streaks():
    """Retorna streak atual (dias consecutivos) e dados de hoje"""
    with get_db() as conn:
        # Dados de hoje
        hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()
        hoje_data = dict(hoje) if hoje else {"data": today_str(), "horas_estudadas": 0, "questoes_resolvidas": 0, "flashcards_revisados": 0}

        streak_info = calculate_streak(conn)

    return {
        "streak_atual": streak_info["streak_atual"],
        "melhor_streak": streak_info["melhor_streak"],
        "hoje": hoje_data
    }


@router.get("/api/metas")
def get_metas():
    with get_db() as conn:
        config = conn.execute("SELECT * FROM metas_config WHERE id = 1").fetchone()
        hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()

    config_dict = dict(config) if config else {"meta_horas": 3.0, "meta_questoes": 30, "meta_flashcards": 10, "meta_paginas": 20}
    hoje_dict = dict(hoje) if hoje else {"horas_estudadas": 0, "questoes_resolvidas": 0, "flashcards_revisados": 0}

    return {
        "config": config_dict,
        "progresso": {
            "horas": hoje_dict.get("horas_estudadas", 0),
            "questoes": hoje_dict.get("questoes_resolvidas", 0),
            "flashcards": hoje_dict.get("flashcards_revisados", 0)
        }
    }


@router.put("/api/metas")
def update_metas(body: MetasUpdate):
    with get_db() as conn:
        conn.execute("""
            UPDATE metas_config SET meta_horas = ?, meta_questoes = ?, meta_flashcards = ?, meta_paginas = ?
            WHERE id = 1
        """, (body.meta_horas, body.meta_questoes, body.meta_flashcards, body.meta_paginas))
        conn.commit()
    return {"ok": True}


@router.get("/api/gamification")
def get_gamification():
    """Retorna XP, nível, badges e progresso do usuário"""
    with get_db() as conn:
        # Calcular XP baseado nas atividades
        horas = conn.execute("SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo").fetchone()[0]
        questoes_total = conn.execute("SELECT COUNT(*) FROM questoes_respostas").fetchone()[0]
        questoes_certas = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE acertou = 1").fetchone()[0]
        flashcards_rev = conn.execute("SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks").fetchone()[0]
        topicos_concluidos = conn.execute("SELECT COUNT(*) FROM edital WHERE status = 'Concluído'").fetchone()[0]
        simulados_feitos = conn.execute("SELECT COUNT(*) FROM simulados WHERE status = 'finalizado'").fetchone()[0]

        # Streak atual
        streak_info = calculate_streak(conn)
        streak = streak_info["streak_atual"]

    # Calcular XP
    xp = int(
        horas * 100 +
        questoes_total * 10 +
        questoes_certas * 5 +
        flashcards_rev * 5 +
        topicos_concluidos * 25 +
        simulados_feitos * 50 +
        (streak // 7) * 200
    )

    nivel = (xp // LEVEL_XP) + 1
    xp_no_nivel = xp % LEVEL_XP
    xp_para_proximo = LEVEL_XP

    # Verificar badges
    accuracy = (questoes_certas / questoes_total * 100) if questoes_total > 0 else 0
    badges_earned = []
    for badge in BADGES:
        earned = False
        cond = badge["condition"]
        if cond == "horas >= 1" and horas >= 1: earned = True
        elif cond == "horas >= 10" and horas >= 10: earned = True
        elif cond == "horas >= 50" and horas >= 50: earned = True
        elif cond == "questoes >= 1" and questoes_total >= 1: earned = True
        elif cond == "questoes >= 100" and questoes_total >= 100: earned = True
        elif cond == "questoes >= 500" and questoes_total >= 500: earned = True
        elif cond == "streak >= 7" and streak >= 7: earned = True
        elif cond == "streak >= 30" and streak >= 30: earned = True
        elif cond == "simulados >= 1" and simulados_feitos >= 1: earned = True
        elif cond == "accuracy >= 80" and accuracy >= 80 and questoes_total >= 20: earned = True
        elif cond == "topicos >= 10" and topicos_concluidos >= 10: earned = True
        elif cond == "topicos >= 50" and topicos_concluidos >= 50: earned = True

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
def conquistas_diarias():
    """Gera missões diárias baseadas no progresso"""
    with get_db() as conn:
        # Buscar matérias menos estudadas
        mat_fraca = conn.execute("""
            SELECT materia FROM edital WHERE status != 'Concluído'
            GROUP BY materia ORDER BY SUM(horas_estudadas) ASC LIMIT 5
        """).fetchall()

        # Dados de hoje
        hoje = conn.execute("SELECT * FROM streaks WHERE data = ?", (today_str(),)).fetchone()

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
def list_desafios():
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM desafios ORDER BY finalizado ASC, created_at DESC").fetchall()
    return [dict(r) for r in rows]


@router.post("/api/desafios")
def create_desafio(body: DesafioCreate):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO desafios (titulo, meta_tipo, meta_valor, materia, dias, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (body.titulo, body.meta_tipo, body.meta_valor, body.materia, body.dias, today_str()))
        conn.commit()
    return {"id": cur.lastrowid, "ok": True}

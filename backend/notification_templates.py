"""Smart notification templates with personality and escalating urgency."""
import random

# ============================================================
# NOTIFICATION PERSONALITY: Motivational study coach
# ============================================================

STREAK_TEMPLATES = {
    "gentle": [  # First reminder (18:00)
        {"title": "📚 Hora de estudar!", "body": "Seu streak de {streak} dias está esperando. Que tal {suggestion}?"},
        {"title": "🎯 Bora manter o ritmo?", "body": "Ainda dá tempo de estudar hoje! {streak} dias sem parar 💪"},
        {"title": "💡 Dica do dia", "body": "15 minutos de revisão já contam! Mantenha seu streak de {streak} dias."},
    ],
    "urgent": [  # Second reminder (20:00)
        {"title": "⚠️ Streak em risco!", "body": "Faltam poucas horas! Não perca {streak} dias de dedicação."},
        {"title": "🔥 Não deixe o fogo apagar!", "body": "{streak} dias de estudo estão em jogo. 10 minutos resolvem!"},
        {"title": "😱 Seu streak vai quebrar!", "body": "Ainda não estudou hoje! {streak} dias de esforço em risco."},
    ],
    "critical": [  # Last chance (22:00)
        {"title": "🚨 ÚLTIMA CHANCE!", "body": "Seu streak de {streak} dias acaba à meia-noite! Corra!"},
        {"title": "⏰ Meia-noite se aproxima!", "body": "2 horas para salvar {streak} dias de dedicação. Vai deixar escapar?"},
    ],
}

FLASHCARD_TEMPLATES = [
    {"title": "🧠 Revisões pendentes!", "body": "{count} flashcards te esperando. Sua memória agradece!"},
    {"title": "📝 Hora de revisar!", "body": "{count} cards para hoje. Espaçamento é a chave da retenção!"},
    {"title": "🎴 Não esqueça seus cards!", "body": "{count} revisões atrasadas. Quanto mais adia, mais esquece!"},
]

EXAM_TEMPLATES = {
    "30_days": [
        {"title": "📅 30 dias para a prova!", "body": "{exam_name}: foque nos tópicos mais cobrados de {banca}."},
        {"title": "⏳ 1 mês para {exam_name}!", "body": "Hora de intensificar! Priorize questões e revisões."},
    ],
    "14_days": [
        {"title": "⚡ 2 semanas para {exam_name}!", "body": "Reta final! Simulados e revisão são prioridade agora."},
    ],
    "7_days": [
        {"title": "🚀 1 SEMANA para {exam_name}!", "body": "Revise súmulas, flashcards e faça 1 simulado por dia!"},
    ],
    "3_days": [
        {"title": "🔥 3 DIAS! {exam_name}", "body": "Revisão leve + descanso. Confie no seu preparo!"},
    ],
    "1_day": [
        {"title": "🌟 AMANHÃ É O DIA!", "body": "{exam_name}: descanse, confie em você. Boa prova! 🍀"},
    ],
}

CHALLENGE_TEMPLATES = [
    {"title": "🏆 Desafio expirando!", "body": "'{titulo}' acaba amanhã! Você está em {pct}%. Dá pra completar!"},
    {"title": "⏰ Desafio quase acabando!", "body": "Falta pouco para '{titulo}'! {progresso}/{meta} — corra!"},
]

CELEBRATION_TEMPLATES = [
    {"title": "🎉 Parabéns!", "body": "Streak de {streak} dias! Você é uma máquina! 🔥"},
    {"title": "🏅 Nova conquista!", "body": "Badge '{badge_name}' desbloqueado! Continue assim!"},
    {"title": "📈 Evoluindo!", "body": "Seu domínio em {materia} subiu para {mastery}%! 💪"},
]

INACTIVITY_TEMPLATES = {
    "2_days": [
        {"title": "👋 Sentimos sua falta!", "body": "2 dias sem estudar. Voltar agora ainda salva o momentum!"},
    ],
    "5_days": [
        {"title": "😢 Onde você foi?", "body": "5 dias longe... Seus flashcards estão acumulando. Volta!"},
    ],
    "7_days": [
        {"title": "📚 Seu concurso não espera!", "body": "1 semana sem estudar. Comece com apenas 10 minutos hoje?"},
    ],
}


def get_streak_notification(streak: int, urgency: str = "gentle", suggestion: str = "resolver 5 questões") -> dict:
    """Returns a streak notification with appropriate urgency level."""
    templates = STREAK_TEMPLATES.get(urgency, STREAK_TEMPLATES["gentle"])
    template = random.choice(templates)
    return {
        "title": template["title"],
        "body": template["body"].format(streak=streak, suggestion=suggestion),
        "tag": f"streak-{urgency}",
        "url": "/dashboard.html"
    }


def get_flashcard_notification(count: int) -> dict:
    """Returns a flashcard reminder notification."""
    template = random.choice(FLASHCARD_TEMPLATES)
    return {
        "title": template["title"],
        "body": template["body"].format(count=count),
        "tag": "flashcards",
        "url": "/dashboard.html#flashcards"
    }


def get_exam_notification(exam_name: str, days_until: int, banca: str = "") -> dict:
    """Returns an exam countdown notification with urgency based on days remaining."""
    if days_until <= 1:
        key = "1_day"
    elif days_until <= 3:
        key = "3_days"
    elif days_until <= 7:
        key = "7_days"
    elif days_until <= 14:
        key = "14_days"
    else:
        key = "30_days"
    templates = EXAM_TEMPLATES.get(key, EXAM_TEMPLATES["30_days"])
    template = random.choice(templates)
    return {
        "title": template["title"].format(exam_name=exam_name),
        "body": template["body"].format(exam_name=exam_name, banca=banca),
        "tag": f"exam-{days_until}",
        "url": "/dashboard.html",
        "requireInteraction": days_until <= 3
    }


def get_challenge_notification(titulo: str, progresso: int, meta: int, pct: int) -> dict:
    """Returns a challenge expiration notification."""
    template = random.choice(CHALLENGE_TEMPLATES)
    return {
        "title": template["title"],
        "body": template["body"].format(titulo=titulo, progresso=progresso, meta=meta, pct=pct),
        "tag": "challenge-expiring",
        "url": "/dashboard.html"
    }


def get_inactivity_notification(days_inactive: int) -> dict:
    """Returns an inactivity notification based on how many days away."""
    if days_inactive >= 7:
        key = "7_days"
    elif days_inactive >= 5:
        key = "5_days"
    else:
        key = "2_days"
    templates = INACTIVITY_TEMPLATES.get(key, INACTIVITY_TEMPLATES["2_days"])
    template = random.choice(templates)
    return {
        "title": template["title"],
        "body": template["body"],
        "tag": "inactivity",
        "url": "/dashboard.html"
    }


def get_study_suggestion(conn, user_id) -> str:
    """Returns a contextual study suggestion based on user's weakest area."""
    fraca = conn.execute("""
        SELECT q.materia FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia HAVING COUNT(*) >= 3
        ORDER BY (CAST(SUM(qr.acertou) AS REAL) / COUNT(*)) ASC LIMIT 1
    """, (user_id,)).fetchone()
    if fraca:
        return f"resolver questões de {fraca[0]}"
    return "revisar seus flashcards pendentes"

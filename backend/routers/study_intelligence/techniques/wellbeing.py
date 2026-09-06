"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, Query

from database import get_db_session
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# BURNOUT DETECTION — Detecção de risco de esgotamento
# ============================================================


def _detect_burnout(conn, user_id: int) -> dict:
    """Detecta risco de burnout baseado em horas de estudo vs meta.

    Critérios:
    - horas > meta * 1.5 por 5+ dias consecutivos: risco moderado
    - horas > meta * 2.0 por 3+ dias consecutivos: risco alto
    """
    # Obter meta de horas
    metas = conn.execute("SELECT meta_horas FROM metas_config WHERE user_id = ?", (user_id,)).fetchone()
    meta_horas = metas[0] if metas else 3.0

    # Obter últimos 7 dias de streaks
    sete_dias_atras = (date.today() - timedelta(days=6)).isoformat()
    rows = conn.execute(
        """
        SELECT data, horas_estudadas FROM streaks
        WHERE data >= ? AND user_id = ?
        ORDER BY data DESC
    """,
        (sete_dias_atras, user_id),
    ).fetchall()

    if not rows:
        return {
            "risk": None,
            "dias_overwork": 0,
            "media_horas_7d": 0,
            "meta_horas": meta_horas,
            "sugestao": None,
        }

    # Calcular médias e dias de overwork
    horas_list = [r["horas_estudadas"] or 0 for r in rows]
    media_horas_7d = round(sum(horas_list) / len(horas_list), 1) if horas_list else 0

    # Checar dias consecutivos de overwork (do mais recente para trás)
    dias_overwork_150 = 0  # > meta * 1.5
    dias_overwork_200 = 0  # > meta * 2.0

    # Contar dias consecutivos acima de 1.5x
    for h in horas_list:
        if h > meta_horas * 1.5:
            dias_overwork_150 += 1
        else:
            break

    # Contar dias consecutivos acima de 2.0x
    for h in horas_list:
        if h > meta_horas * 2.0:
            dias_overwork_200 += 1
        else:
            break

    # Determinar nível de risco
    risk = None
    sugestao = None

    if dias_overwork_200 >= 3:
        risk = "alto"
        sugestao = "⚠️ Risco alto de burnout! Você está estudando mais que o dobro da meta há vários dias. Considere um dia de descanso completo ou reduza significativamente a carga."
    elif dias_overwork_150 >= 5:
        risk = "moderado"
        sugestao = "Considere um dia de descanso ativo ou redução de carga. Estudar demais pode prejudicar a retenção de longo prazo."
    elif dias_overwork_150 >= 3:
        risk = "moderado"
        sugestao = (
            "Sua carga de estudo está elevada. Intercale dias mais leves para otimizar a consolidação de memória."
        )

    return {
        "risk": risk,
        "dias_overwork": max(dias_overwork_150, dias_overwork_200),
        "media_horas_7d": media_horas_7d,
        "meta_horas": meta_horas,
        "sugestao": sugestao,
    }


@router.get(
    "/api/study-intelligence/burnout",
    summary="Burnout Detection",
    description="Detecta risco de esgotamento baseado em padrão de horas de estudo vs meta configurada.",
)
def burnout_detection(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna análise de risco de burnout baseado nos últimos 7 dias."""
    return _detect_burnout(conn, user_id)


# ============================================================
# BLOCKED PRACTICE DETECTION — Rohrer (2012)
# Interleaving produz +20-40% retenção vs prática em bloco
# ============================================================


@router.get(
    "/api/study-intelligence/blocked-practice",
    summary="Blocked Practice Detection",
    description="""Detecta quando o usuário está estudando em bloco (mesma matéria por muito tempo)
e sugere intercalar. Interleaving produz 20-40% mais retenção que blocked practice (Rohrer 2012).""",
)
def blocked_practice_detection(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Analisa sessão atual e retorna alerta se detectar prática em bloco."""
    hoje = today_str()

    # Verificar últimas 15 respostas de questões de hoje
    ultimas = conn.execute(
        """
        SELECT q.materia, qr.data, qr.id
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data = ?
        ORDER BY qr.id DESC LIMIT 15
    """,
        (user_id, hoje),
    ).fetchall()

    if len(ultimas) < 5:
        return {"blocked": False, "message": "Dados insuficientes para análise", "streak_count": 0}

    # Contar sequência consecutiva da mesma matéria (mais recentes primeiro)
    current_materia = ultimas[0]["materia"]
    streak = 0
    for r in ultimas:
        if r["materia"] == current_materia:
            streak += 1
        else:
            break

    # Verificar também sessões de estudo (timer/pomodoro) do mesmo tópico
    sessao_mesma = conn.execute(
        """
        SELECT SUM(horas) as total FROM sessoes_estudo
        WHERE user_id = ? AND data = ? AND materia = ?
    """,
        (user_id, hoje, current_materia),
    ).fetchone()
    horas_mesma = sessao_mesma["total"] or 0

    # Alertar se: 8+ questões seguidas da mesma matéria OU 1.5h+ da mesma matéria hoje
    is_blocked = streak >= 8 or horas_mesma >= 1.5

    # Sugerir matéria diferente para intercalar
    sugestao_materia = None
    if is_blocked:
        # Buscar matéria menos estudada hoje
        outras = conn.execute(
            """
            SELECT DISTINCT materia FROM edital
            WHERE user_id = ? AND materia != ? AND arquivado = 0
            AND materia NOT IN (
                SELECT DISTINCT q.materia FROM questoes_respostas qr
                JOIN questoes q ON q.id = qr.questao_id
                WHERE qr.user_id = ? AND qr.data = ?
                AND qr.id > (SELECT MAX(id) - 5 FROM questoes_respostas WHERE user_id = ? AND data = ?)
            )
            ORDER BY RANDOM() LIMIT 1
        """,
            (user_id, current_materia, user_id, hoje, user_id, hoje),
        ).fetchone()
        if outras:
            sugestao_materia = outras["materia"]
        else:
            # Qualquer outra matéria do ciclo
            outra = conn.execute(
                """
                SELECT materia FROM ciclo_estudos
                WHERE user_id = ? AND ativo = 1 AND materia != ?
                ORDER BY horas_cumpridas / horas_alvo ASC LIMIT 1
            """,
                (user_id, current_materia),
            ).fetchone()
            if outra:
                sugestao_materia = outra["materia"]

    motivo = ""
    if streak >= 8:
        motivo = f"Você respondeu {streak} questões seguidas de {current_materia}."
    elif horas_mesma >= 1.5:
        motivo = f"Você já estudou {horas_mesma:.1f}h de {current_materia} hoje."

    return {
        "blocked": is_blocked,
        "materia_atual": current_materia,
        "streak_count": streak,
        "horas_materia_hoje": round(horas_mesma, 2),
        "motivo": motivo,
        "sugestao": f"Intercale com {sugestao_materia} para melhorar retenção em 20-40%." if sugestao_materia else "",
        "sugestao_materia": sugestao_materia,
        "tecnica": "Interleaving (Rohrer 2012): alternar matérias durante o estudo produz aprendizado mais duradouro que estudar uma matéria por vez.",
    }


# ============================================================
# SLEEP CONSOLIDATION — Born & Wilhelm (2012)
# Revisão antes de dormir + ao acordar = +20% retenção
# ============================================================


@router.get(
    "/api/study-intelligence/sleep-consolidation",
    summary="Sleep Consolidation Review",
    description="""Retorna itens ideais para revisão pré-sono (21h-1h) e matinal (5h-9h).
Baseado em Born & Wilhelm (2012): memórias são consolidadas durante o sono.
Revisar material difícil antes de dormir e re-testar ao acordar melhora retenção em ~20%.""",
)
def sleep_consolidation(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna flashcards e questões para revisão de consolidação."""
    from datetime import datetime

    hora_atual = datetime.now().hour
    hoje = today_str()
    ontem = (date.today() - timedelta(days=1)).isoformat()

    # Determinar modo: noturno (21h-1h) ou matinal (5h-9h)
    if hora_atual >= 21 or hora_atual <= 1:
        modo = "noturno"
    elif 5 <= hora_atual <= 9:
        modo = "matinal"
    else:
        modo = "fora_janela"

    # === FLASHCARDS para consolidação ===
    # Prioridade: erros do dia + cards com baixo stability + cards revisados hoje com difficulty alta
    flashcards_consolidacao = []

    if modo == "noturno":
        # Noturno: itens ERRADOS hoje + cards que foram difíceis hoje
        # 1. Flashcards que errou hoje (quality < 3)
        fc_errados = conn.execute(
            """
            SELECT f.id, f.pergunta, f.resposta, f.materia, f.stability, f.difficulty
            FROM flashcards f
            WHERE f.user_id = ? AND f.difficulty > 5
            AND f.id IN (
                SELECT id FROM flashcards WHERE user_id = ? AND proxima_revisao = ?
            )
            ORDER BY f.difficulty DESC
            LIMIT 5
        """,
            (user_id, user_id, (date.today() + timedelta(days=1)).isoformat()),
        ).fetchall()
        flashcards_consolidacao.extend([dict(r) for r in fc_errados])

        # 2. Flashcards novos vistos hoje (stability baixa = frágil)
        fc_frageis = conn.execute(
            """
            SELECT id, pergunta, resposta, materia, stability, difficulty
            FROM flashcards
            WHERE user_id = ? AND stability > 0 AND stability <= 3
            AND proxima_revisao > ?
            ORDER BY stability ASC
            LIMIT 5
        """,
            (user_id, hoje),
        ).fetchall()
        for r in fc_frageis:
            if r["id"] not in {f["id"] for f in flashcards_consolidacao}:
                flashcards_consolidacao.append(dict(r))

    elif modo == "matinal":
        # Matinal: re-testar os mesmos itens da noite anterior (ou erros de ontem)
        # Cards com próxima revisão = hoje (normal FSRS) + erros de ontem
        fc_hoje = conn.execute(
            """
            SELECT id, pergunta, resposta, materia, stability, difficulty
            FROM flashcards
            WHERE user_id = ? AND proxima_revisao <= ?
            ORDER BY difficulty DESC, stability ASC
            LIMIT 8
        """,
            (user_id, hoje),
        ).fetchall()
        flashcards_consolidacao = [dict(r) for r in fc_hoje]

    # === QUESTÕES para consolidação ===
    questoes_consolidacao = []

    if modo == "noturno":
        # Questões erradas hoje
        q_erradas = conn.execute(
            """
            SELECT q.id, q.enunciado, q.materia, q.resposta_correta, q.explicacao
            FROM questoes q
            JOIN questoes_respostas qr ON qr.questao_id = q.id
            WHERE qr.user_id = ? AND qr.data = ? AND qr.acertou = 0
            ORDER BY qr.id DESC
            LIMIT 5
        """,
            (user_id, hoje),
        ).fetchall()
        questoes_consolidacao = [dict(r) for r in q_erradas]

    elif modo == "matinal":
        # Questões erradas ontem (re-testar após consolidação do sono)
        q_ontem = conn.execute(
            """
            SELECT q.id, q.enunciado, q.materia, q.resposta_correta, q.explicacao
            FROM questoes q
            JOIN questoes_respostas qr ON qr.questao_id = q.id
            WHERE qr.user_id = ? AND qr.data = ? AND qr.acertou = 0
            ORDER BY RANDOM()
            LIMIT 5
        """,
            (user_id, ontem),
        ).fetchall()
        questoes_consolidacao = [dict(r) for r in q_ontem]

    # Mensagem contextual
    mensagens = {
        "noturno": "🌙 Revisão pré-sono: consolidação de memória durante o sono melhora retenção em ~20%. Revise estes itens difíceis antes de dormir.",
        "matinal": "☀️ Revisão matinal: re-teste após o sono. Seu cérebro consolidou estas memórias durante a noite — agora é hora de fortalecer.",
        "fora_janela": "⏰ As janelas ideais de consolidação são: 21h-1h (pré-sono) e 5h-9h (matinal). Volte nesses horários para máxima eficácia.",
    }

    return {
        "modo": modo,
        "hora_atual": hora_atual,
        "mensagem": mensagens[modo],
        "flashcards": flashcards_consolidacao[:8],
        "questoes": questoes_consolidacao[:5],
        "total_flashcards": len(flashcards_consolidacao),
        "total_questoes": len(questoes_consolidacao),
        "tecnica": "Sleep Consolidation (Born & Wilhelm 2012): memórias são transferidas do hipocampo para o neocórtex durante o sono. Revisar antes de dormir e re-testar ao acordar maximiza esse processo.",
        "dica": "Não estude conteúdo NOVO antes de dormir — apenas REVISE o que já viu hoje."
        if modo == "noturno"
        else "Tente recordar ANTES de olhar a resposta (retrieval practice)."
        if modo == "matinal"
        else "",
    }


# ============================================================
# ADAPTIVE BREAK SCHEDULING — Ultradian Rhythms + Fatigue Detection
# Pausas inteligentes baseadas em fadiga real, não timer fixo
# ============================================================


@router.get(
    "/api/study-intelligence/adaptive-break",
    summary="Adaptive Break Scheduling",
    description="""Calcula o momento ideal para pausa baseado em fadiga real:
tempo de resposta crescente + taxa de acerto decrescente + duração da sessão.
Baseado em ritmos ultradianos (~90min) e detecção de fadiga cognitiva.""",
)
def adaptive_break(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Analisa sessão atual e recomenda se deve pausar ou continuar."""
    hoje = today_str()

    # Últimas 20 respostas de hoje com tempo
    respostas = conn.execute(
        """
        SELECT qr.acertou, qr.tempo_segundos, qr.id
        FROM questoes_respostas qr
        WHERE qr.user_id = ? AND qr.data = ? AND qr.tempo_segundos > 0
        ORDER BY qr.id ASC
    """,
        (user_id, hoje),
    ).fetchall()

    if len(respostas) < 5:
        return {
            "deve_pausar": False,
            "fadiga_nivel": "insuficiente",
            "motivo": "Menos de 5 respostas hoje — dados insuficientes para análise.",
            "sugestao_pausa_min": 0,
            "sessao_min_estimado": 0,
        }

    # Dividir em primeira metade e segunda metade da sessão
    meio = len(respostas) // 2
    primeira_metade = respostas[:meio]
    segunda_metade = respostas[meio:]

    # Métricas da primeira metade
    tempo_medio_inicio = sum(r["tempo_segundos"] for r in primeira_metade) / len(primeira_metade)
    acerto_inicio = sum(1 for r in primeira_metade if r["acertou"]) / len(primeira_metade)

    # Métricas da segunda metade (recente)
    tempo_medio_fim = sum(r["tempo_segundos"] for r in segunda_metade) / len(segunda_metade)
    acerto_fim = sum(1 for r in segunda_metade if r["acertou"]) / len(segunda_metade)

    # Últimas 5 respostas (janela curta para detecção imediata)
    ultimas5 = respostas[-5:]
    acerto_ultimas5 = sum(1 for r in ultimas5 if r["acertou"]) / 5

    # Calcular indicadores de fadiga
    tempo_aumento_pct = (
        ((tempo_medio_fim - tempo_medio_inicio) / tempo_medio_inicio * 100) if tempo_medio_inicio > 0 else 0
    )
    acerto_queda_pct = ((acerto_inicio - acerto_fim) / acerto_inicio * 100) if acerto_inicio > 0 else 0

    # Tempo total de sessão (estimado pela diferença entre primeiro e último registro)
    # Aproximar pelo número de questões × tempo médio
    sessao_min = sum(r["tempo_segundos"] for r in respostas) / 60

    # === Determinar nível de fadiga ===
    # Critérios:
    # - Tempo de resposta aumentou > 30% → fadiga leve
    # - Tempo aumentou > 50% OU acerto caiu > 20% → fadiga moderada
    # - Tempo aumentou > 70% E acerto caiu > 30% → fadiga alta
    # - Sessão > 90min (ritmo ultradiano) → sugerir pausa independente
    if tempo_aumento_pct > 70 and acerto_queda_pct > 30:
        fadiga = "alta"
        deve_pausar = True
        pausa_min = 20
    elif tempo_aumento_pct > 50 or acerto_queda_pct > 20:
        fadiga = "moderada"
        deve_pausar = True
        pausa_min = 10
    elif tempo_aumento_pct > 30 or sessao_min > 90:
        fadiga = "leve"
        deve_pausar = sessao_min > 60  # Só sugere se já passou 60min
        pausa_min = 5
    else:
        fadiga = "baixa"
        deve_pausar = False
        pausa_min = 0

    # Sugerir atividade de pausa
    if pausa_min >= 15:
        atividade_pausa = "Levante, hidrate-se, faça alongamento. Considere uma caminhada curta."
    elif pausa_min >= 10:
        atividade_pausa = "Respiração 4-4-6 (2min) + água. Evite telas."
    elif pausa_min > 0:
        atividade_pausa = "Feche os olhos 2min. Respire fundo. Depois continue."
    else:
        atividade_pausa = ""

    # Construir motivo detalhado
    motivos = []
    if tempo_aumento_pct > 30:
        motivos.append(f"Tempo de resposta aumentou {tempo_aumento_pct:.0f}%")
    if acerto_queda_pct > 15:
        motivos.append(f"Taxa de acerto caiu {acerto_queda_pct:.0f}%")
    if sessao_min > 90:
        motivos.append(f"Sessão de {sessao_min:.0f}min (ritmo ultradiano: pausa a cada ~90min)")
    if acerto_ultimas5 < 0.4:
        motivos.append(f"Últimas 5 questões: apenas {int(acerto_ultimas5 * 100)}% de acerto")

    return {
        "deve_pausar": deve_pausar,
        "fadiga_nivel": fadiga,
        "motivo": " · ".join(motivos) if motivos else "Performance estável. Continue!",
        "sugestao_pausa_min": pausa_min,
        "atividade_pausa": atividade_pausa,
        "sessao_min_estimado": round(sessao_min, 1),
        "metricas": {
            "total_questoes_hoje": len(respostas),
            "tempo_medio_inicio_seg": round(tempo_medio_inicio, 1),
            "tempo_medio_fim_seg": round(tempo_medio_fim, 1),
            "acerto_inicio_pct": round(acerto_inicio * 100, 1),
            "acerto_fim_pct": round(acerto_fim * 100, 1),
            "tempo_aumento_pct": round(tempo_aumento_pct, 1),
            "acerto_queda_pct": round(acerto_queda_pct, 1),
        },
        "tecnica": "Adaptive Break (ritmos ultradianos + detecção de fadiga): pausar quando a performance CAI é mais eficiente que pausar por timer fixo. Produtividade pós-pausa aumenta 15-20%.",
    }


# ============================================================
# EXAM ANXIETY EXPOSURE — Exposição Gradual a Pressão de Prova
# Baseado em literatura de test anxiety (Zeidner 1998, Hembree 1988)
# Dessensibilização sistemática: pressão gradual reduz ansiedade
# ============================================================


@router.get(
    "/api/study-intelligence/anxiety-exposure",
    summary="Exam Anxiety Exposure Config",
    description="""Gera configuração de simulado com pressão gradual para dessensibilização.
4 níveis progressivos de estresse simulado:
- Nível 1 (Confortável): tempo normal, sem pressão
- Nível 2 (Moderado): tempo -20%, cronômetro visível
- Nível 3 (Realista): tempo -20% + nota de corte visível + penalização C/E
- Nível 4 (Alta pressão): tempo -30% + nota corte + penalização + ranking

Baseado em Zeidner (1998): exposição gradual a condições de prova reduz ansiedade
em 40-60% após 4-6 sessões. Hembree (1988): meta-análise confirma eficácia.""",
)
def anxiety_exposure_config(
    nivel: int = Query(1, description="Nível de pressão (1-4)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna configuração de simulado com nível de ansiedade progressivo."""

    # Detectar nível recomendado baseado no histórico
    nivel_recomendado = 1
    try:
        simulados_feitos = conn.execute(
            """
            SELECT COUNT(*) FROM simulados WHERE user_id = ? AND status = 'finalizado'
        """,
            (user_id,),
        ).fetchone()[0]

        # Progresso gradual: a cada 3 simulados, sobe 1 nível
        if simulados_feitos >= 12:
            nivel_recomendado = 4
        elif simulados_feitos >= 8:
            nivel_recomendado = 3
        elif simulados_feitos >= 4:
            nivel_recomendado = 2
        else:
            nivel_recomendado = 1
    except Exception:
        pass

    nivel = max(1, min(4, nivel))

    # Configurações por nível
    configs = {
        1: {
            "nome": "Confortável",
            "emoji": "😊",
            "tempo_fator": 1.0,  # Tempo normal
            "penalizacao": False,
            "nota_corte_visivel": False,
            "cronometro_visivel": False,
            "ranking_visivel": False,
            "distracoes": False,
            "mensagem_pressao": "",
            "descricao": "Simulado normal, sem pressão. Foque em aprender.",
        },
        2: {
            "nome": "Moderado",
            "emoji": "😐",
            "tempo_fator": 0.80,  # 20% menos tempo
            "penalizacao": False,
            "nota_corte_visivel": False,
            "cronometro_visivel": True,  # Cronômetro regressivo visível
            "ranking_visivel": False,
            "distracoes": False,
            "mensagem_pressao": "⏱️ Tempo reduzido em 20%. Gerencie bem cada questão.",
            "descricao": "Tempo apertado + cronômetro visível. Treine gestão de tempo.",
        },
        3: {
            "nome": "Realista",
            "emoji": "😰",
            "tempo_fator": 0.80,
            "penalizacao": True,  # -1 por erro (estilo CESPE)
            "nota_corte_visivel": True,  # Nota de corte aparece durante o simulado
            "cronometro_visivel": True,
            "ranking_visivel": False,
            "distracoes": False,
            "mensagem_pressao": "⚠️ Penalização ativa: 1 erro anula 1 acerto. Nota de corte: 60%.",
            "descricao": "Condições de prova CESPE: penalização + nota de corte visível.",
        },
        4: {
            "nome": "Alta Pressão",
            "emoji": "🥵",
            "tempo_fator": 0.70,  # 30% menos tempo
            "penalizacao": True,
            "nota_corte_visivel": True,
            "cronometro_visivel": True,
            "ranking_visivel": True,  # Mostra posição vs outros candidatos (bots)
            "distracoes": True,  # Alertas aleatórios simulando ambiente de prova
            "mensagem_pressao": "🔥 ALTA PRESSÃO: tempo -30%, penalização, nota de corte, ranking ao vivo. Respire fundo.",
            "descricao": "Simulação máxima de estresse. Se passar aqui, passa na prova real.",
        },
    }

    config = configs[nivel]

    # Calcular tempo com fator
    tempo_base_min = 180  # 3h padrão
    try:
        # Buscar do edital_info se existir
        ei = conn.execute("SELECT tempo_prova_min FROM edital_info WHERE user_id = ? LIMIT 1", (user_id,)).fetchone()
        if ei and ei[0]:
            tempo_base_min = ei[0]
    except Exception:
        pass

    tempo_ajustado = int(tempo_base_min * config["tempo_fator"])

    # Nota de corte
    nota_corte = 60.0  # Padrão para maioria dos concursos
    try:
        nc = conn.execute(
            "SELECT nota_corte FROM notas_corte WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user_id,)
        ).fetchone()
        if nc:
            nota_corte = nc[0]
    except Exception:
        pass

    # Dicas anti-ansiedade baseadas no nível
    dicas_anti_ansiedade = [
        "🫁 Antes de começar: 3 respirações profundas (4s inspira, 4s segura, 6s expira)",
        "📋 Estratégia: leia todas as questões antes, marque as fáceis primeiro",
        "🧠 Se travar: pule e volte depois. Não gaste mais de 3min numa questão",
    ]
    if nivel >= 3:
        dicas_anti_ansiedade.append("⚡ Penalização: se < 60% de certeza, DEIXE EM BRANCO")
        dicas_anti_ansiedade.append("🎯 Foco no que SABE. Não tente resolver tudo.")
    if nivel >= 4:
        dicas_anti_ansiedade.append(
            "💪 Lembre: isso é TREINO. A prova real será mais fácil porque você já treinou sob pressão."
        )

    return {
        "nivel": nivel,
        "nivel_recomendado": nivel_recomendado,
        "config": config,
        "tempo_base_min": tempo_base_min,
        "tempo_ajustado_min": tempo_ajustado,
        "nota_corte": nota_corte,
        "dicas_anti_ansiedade": dicas_anti_ansiedade,
        "progresso_exposicao": {
            "simulados_feitos": simulados_feitos if "simulados_feitos" in dir() else 0,
            "proximo_nivel_em": max(0, (nivel * 4) - (simulados_feitos if "simulados_feitos" in dir() else 0)),
        },
        "tecnica": "Exam Anxiety Exposure (Zeidner 1998): exposição gradual a condições estressantes reduz ansiedade em 40-60% após 4-6 sessões. Seu cérebro aprende que 'pressão não é perigo'.",
    }


@router.post("/api/study-intelligence/anxiety-exposure/registrar", summary="Registrar resultado de sessão de exposição")
def anxiety_exposure_registrar(
    nivel: int = Body(1),
    nota: float = Body(0),
    tempo_seg: int = Body(0),
    completou: bool = Body(True),
    ansiedade_antes: int = Body(5, description="Nível de ansiedade antes (1-10)"),
    ansiedade_depois: int = Body(5, description="Nível de ansiedade depois (1-10)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra resultado da sessão de exposição para tracking de progresso."""
    from datetime import datetime

    conn.execute("""
        CREATE TABLE IF NOT EXISTS anxiety_exposure_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            nivel INTEGER NOT NULL,
            nota REAL,
            tempo_seg INTEGER,
            completou INTEGER DEFAULT 1,
            ansiedade_antes INTEGER,
            ansiedade_depois INTEGER,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_anxiety_log_user ON anxiety_exposure_log(user_id)")

    conn.execute(
        """
        INSERT INTO anxiety_exposure_log (user_id, nivel, nota, tempo_seg, completou, ansiedade_antes, ansiedade_depois, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """,
        (
            user_id,
            nivel,
            nota,
            tempo_seg,
            int(completou),
            ansiedade_antes,
            ansiedade_depois,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()

    # Calcular progresso (redução de ansiedade ao longo do tempo)
    historico = conn.execute(
        """
        SELECT ansiedade_antes, ansiedade_depois, nivel, nota
        FROM anxiety_exposure_log WHERE user_id = ?
        ORDER BY id DESC LIMIT 10
    """,
        (user_id,),
    ).fetchall()

    reducao_media = 0
    if historico:
        reducoes = [
            r["ansiedade_antes"] - r["ansiedade_depois"]
            for r in historico
            if r["ansiedade_antes"] and r["ansiedade_depois"]
        ]
        reducao_media = round(sum(reducoes) / len(reducoes), 1) if reducoes else 0

    # Feedback
    diff = ansiedade_antes - ansiedade_depois
    if diff > 2:
        feedback = "🎉 Excelente! Sua ansiedade reduziu significativamente. A exposição está funcionando!"
    elif diff > 0:
        feedback = "👍 Leve redução. Continue praticando — a melhora é progressiva."
    elif diff == 0:
        feedback = "🔄 Ansiedade estável. Normal nos primeiros treinos. Persista!"
    else:
        feedback = "⚠️ Ansiedade aumentou. Tente um nível abaixo na próxima sessão até se adaptar."

    return {
        "ok": True,
        "feedback": feedback,
        "reducao_sessao": diff,
        "reducao_media_historico": reducao_media,
        "sessoes_totais": len(historico),
        "recomendacao": f"Continue no nível {nivel}" if diff >= 0 else f"Tente nível {max(1, nivel - 1)} na próxima",
    }

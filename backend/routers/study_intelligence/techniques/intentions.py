"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Body, Depends, HTTPException

from database import get_db_session
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# IMPLEMENTATION INTENTIONS — Gollwitzer (1999)
# Compromisso pré-sessão aumenta execução em 2-3x
# ============================================================


@router.post(
    "/api/study-intelligence/intention",
    summary="Registrar Implementation Intention",
    description="""Registra um micro-compromisso antes da sessão de estudo.
Baseado em Gollwitzer (1999): 'Eu vou [ação] em [hora] no [local]'
aumenta a probabilidade de execução em 2-3x comparado com apenas 'quero estudar'.""",
)
def register_intention(
    materia: str = Body(...),
    duracao_min: int = Body(30),
    atividade: str = Body("estudo"),
    meta_especifica: str = Body(""),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra intenção de estudo (compromisso pré-sessão)."""
    from datetime import datetime

    # Garantir tabela existe
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_intentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            materia TEXT NOT NULL,
            duracao_min INTEGER NOT NULL,
            atividade TEXT DEFAULT 'estudo',
            meta_especifica TEXT DEFAULT '',
            criado_em TEXT NOT NULL,
            concluido INTEGER DEFAULT 0,
            reflexao TEXT DEFAULT '',
            real_duracao_min INTEGER DEFAULT 0,
            real_acertos INTEGER DEFAULT 0,
            real_questoes INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_intentions_user ON study_intentions(user_id, criado_em)")

    now = datetime.now().isoformat()
    cur = conn.execute(
        """
        INSERT INTO study_intentions (user_id, materia, duracao_min, atividade, meta_especifica, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (user_id, materia, duracao_min, atividade, meta_especifica or "", now),
    )
    conn.commit()

    return {
        "id": cur.lastrowid,
        "ok": True,
        "mensagem": f"✅ Compromisso registrado: {duracao_min}min de {atividade} em {materia}",
        "dica": "Agora COMECE. A intenção registrada aumenta sua chance de execução em 2-3x.",
        "tecnica": "Implementation Intentions (Gollwitzer 1999): declarar especificamente O QUE, QUANDO e COMO reduz procrastinação e aumenta follow-through.",
    }


@router.post("/api/study-intelligence/intention/{id}/concluir", summary="Concluir sessão e confrontar com intenção")
def concluir_intention(
    id: int,
    reflexao: str = Body(""),
    real_duracao_min: int = Body(0),
    real_acertos: int = Body(0),
    real_questoes: int = Body(0),
    nota_foco: int = Body(3, description="Autoavaliação 1-5 do foco durante sessão"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Confronta o realizado com a intenção. Gera feedback metacognitivo."""
    intention = conn.execute("SELECT * FROM study_intentions WHERE id = ? AND user_id = ?", (id, user_id)).fetchone()
    if not intention:
        raise HTTPException(status_code=404, detail="Intenção não encontrada")

    conn.execute(
        """
        UPDATE study_intentions SET
            concluido = 1, reflexao = ?, real_duracao_min = ?,
            real_acertos = ?, real_questoes = ?
        WHERE id = ? AND user_id = ?
    """,
        (reflexao, real_duracao_min, real_acertos, real_questoes, id, user_id),
    )
    conn.commit()

    # Análise: comparar intenção vs realidade
    planejado_min = intention["duracao_min"]
    pct_cumprido = round(real_duracao_min / planejado_min * 100) if planejado_min > 0 else 0

    if pct_cumprido >= 100:
        status = "superou"
        emoji = "🏆"
        feedback = "Superou o planejado! Consistência é a chave."
    elif pct_cumprido >= 80:
        status = "cumpriu"
        emoji = "✅"
        feedback = "Meta cumprida! Bom trabalho."
    elif pct_cumprido >= 50:
        status = "parcial"
        emoji = "⚠️"
        feedback = "Parcialmente cumprido. O que impediu? Anote para a próxima."
    else:
        status = "nao_cumpriu"
        emoji = "❌"
        feedback = "Abaixo do planejado. Tente um compromisso menor amanhã (meta alcançável = motivação)."

    # Histórico de cumprimento (últimos 7 dias)
    try:
        historico = conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN concluido = 1 AND real_duracao_min >= duracao_min * 0.8 THEN 1 ELSE 0 END) as cumpridos
            FROM study_intentions
            WHERE user_id = ? AND criado_em >= date('now', '-7 days')
        """,
            (user_id,),
        ).fetchall()
        total_intencoes = historico[0]["total"] if historico else 0
        cumpridos = historico[0]["cumpridos"] if historico else 0
        taxa_cumprimento = round(cumpridos / total_intencoes * 100) if total_intencoes > 0 else 0
    except Exception:
        taxa_cumprimento = 0
        total_intencoes = 0

    return {
        "status": status,
        "emoji": emoji,
        "feedback": feedback,
        "pct_cumprido": pct_cumprido,
        "planejado_min": planejado_min,
        "real_min": real_duracao_min,
        "taxa_cumprimento_7dias": taxa_cumprimento,
        "total_intencoes_7dias": total_intencoes,
        "sugestao_proxima": f"Tente {max(15, planejado_min - 10)}min amanhã"
        if status == "nao_cumpriu"
        else f"Mantenha {planejado_min}min ou aumente para {planejado_min + 10}min",
        "tecnica": "Reflexão metacognitiva: confrontar intenção vs realidade calibra expectativas futuras e reduz o 'planning fallacy'.",
    }


@router.get("/api/study-intelligence/intention/hoje", summary="Intenções de hoje")
def intencoes_hoje(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna intenções registradas hoje (para exibir no dashboard)."""
    hoje = today_str()
    try:
        rows = conn.execute(
            """
            SELECT * FROM study_intentions
            WHERE user_id = ? AND criado_em >= ? AND criado_em < date(?, '+1 day')
            ORDER BY criado_em
        """,
            (user_id, hoje, hoje),
        ).fetchall()
        intencoes = [dict(r) for r in rows]
    except Exception:
        intencoes = []

    total = len(intencoes)
    concluidas = sum(1 for i in intencoes if i.get("concluido"))
    pendentes = total - concluidas

    return {
        "total": total,
        "concluidas": concluidas,
        "pendentes": pendentes,
        "intencoes": intencoes,
        "mensagem": f"📋 {concluidas}/{total} sessões concluídas hoje"
        if total > 0
        else "Nenhum compromisso registrado hoje. Declare uma intenção para começar!",
    }


@router.get(
    "/api/study-intelligence/temporal-landmark",
    summary="Temporal Landmarks — Fresh Start Effect",
    description="""Detecta 'temporal landmarks' (datas especiais) e sugere metas ambiciosas.
Evidência: Dai et al. (2014) — Segundas, 1° do mês, início de semestre e datas pessoais
funcionam como 'fresh starts' que aumentam motivação e adesão a objetivos.""",
)
def temporal_landmark(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Verifica se hoje é um temporal landmark e sugere boost."""
    hoje = date.today()
    dia_semana = hoje.weekday()  # 0=segunda
    dia_mes = hoje.day

    landmarks = []
    boost_multiplier = 1.0

    # Segunda-feira = fresh start semanal
    if dia_semana == 0:
        landmarks.append(
            {"tipo": "weekly", "emoji": "🌅", "msg": "Nova semana! Fresh start perfeito para metas ambiciosas."}
        )
        boost_multiplier = 1.3

    # 1° do mês = fresh start mensal
    if dia_mes == 1:
        landmarks.append({"tipo": "monthly", "emoji": "📅", "msg": "Novo mês! Hora de definir objetivos maiores."})
        boost_multiplier = 1.5

    # Dia 15 = meio do mês (mini fresh start)
    if dia_mes == 15:
        landmarks.append({"tipo": "mid_month", "emoji": "⚡", "msg": "Metade do mês! Sprint final para suas metas."})
        boost_multiplier = 1.2

    # Primeiro dia útil após feriado/fim de semana prolongado (segunda após domingo)
    if dia_semana == 0 and dia_mes > 1:
        landmarks.append({"tipo": "post_weekend", "emoji": "🚀", "msg": "Energia renovada! Aproveite o momentum."})

    # Verificar streak milestone (múltiplos de 7)
    try:
        streak_row = conn.execute("SELECT streak_atual FROM user_streaks WHERE user_id = ?", (user_id,)).fetchone()
        if streak_row:
            streak = streak_row[0] or 0
            if streak > 0 and streak % 7 == 0:
                landmarks.append(
                    {"tipo": "streak_milestone", "emoji": "🔥", "msg": f"Streak de {streak} dias! Você está imparável."}
                )
                boost_multiplier = max(boost_multiplier, 1.4)
    except Exception:
        pass

    if not landmarks:
        return {
            "is_landmark": False,
            "landmarks": [],
            "boost_multiplier": 1.0,
            "sugestao_meta": None,
        }

    # Buscar meta atual para sugerir boost
    try:
        meta_row = conn.execute(
            "SELECT meta_flashcards, meta_questoes, meta_horas FROM metas_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if meta_row:
            flash_meta = meta_row[0] or 10
            quest_meta = meta_row[1] or 10
            sugestao = {
                "flashcards": int(flash_meta * boost_multiplier),
                "questoes": int(quest_meta * boost_multiplier),
                "mensagem": f"🎯 Que tal {int(flash_meta * boost_multiplier)} flashcards e {int(quest_meta * boost_multiplier)} questões hoje?",
            }
        else:
            sugestao = {
                "flashcards": 15,
                "questoes": 15,
                "mensagem": "🎯 Dia especial! Que tal 15 flashcards e 15 questões?",
            }
    except Exception:
        sugestao = None

    return {
        "is_landmark": True,
        "landmarks": landmarks,
        "boost_multiplier": boost_multiplier,
        "sugestao_meta": sugestao,
    }


@router.get(
    "/api/study-intelligence/spacing-gap",
    summary="Spacing Gap Optimization",
    description="""Calcula o gap ótimo entre sessões baseado na última atividade.
Evidência: Cepeda et al. (2008) — Gap ótimo = 10-20% do intervalo de retenção desejado.
Ex: prova em 30d → gap ideal = 3-6h entre sessões. Prova em 90d → gap = 9-18h.""",
)
def spacing_gap(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Sugere o horário ideal para a próxima sessão de estudo."""
    from datetime import datetime

    from services import get_dias_ate_prova

    agora = datetime.now()

    # Buscar última atividade
    ultima = conn.execute(
        """
        SELECT MAX(created_at) as ultimo FROM sessoes_estudo WHERE user_id = ?
    """,
        (user_id,),
    ).fetchone()

    ultima_atividade = None
    if ultima and ultima[0]:
        try:
            ultima_atividade = datetime.fromisoformat(ultima[0].replace("Z", ""))
        except (ValueError, TypeError):
            pass

    # Calcular gap ótimo baseado nos dias até a prova
    dias_prova = get_dias_ate_prova(conn, user_id)

    if dias_prova and dias_prova > 0:
        # Cepeda (2008): gap ótimo = 10-20% do intervalo de retenção
        gap_horas_min = max(2, dias_prova * 24 * 0.01)  # Mínimo 2h
        gap_horas_max = max(4, dias_prova * 24 * 0.02)  # Máximo razoável
        # Cap em 12h (não faz sentido sugerir voltar em 3 dias)
        gap_horas_min = min(gap_horas_min, 6)
        gap_horas_max = min(gap_horas_max, 12)
    else:
        # Sem prova definida: gap padrão de 4-8h
        gap_horas_min = 4
        gap_horas_max = 8

    # Calcular próxima sessão ideal
    if ultima_atividade:
        horas_desde_ultima = (agora - ultima_atividade).total_seconds() / 3600
        proxima_ideal = ultima_atividade + timedelta(hours=gap_horas_min)
        ja_passou = agora >= proxima_ideal
    else:
        horas_desde_ultima = None
        proxima_ideal = agora
        ja_passou = True

    # Formatar sugestão
    if ja_passou:
        sugestao = "🟢 Hora ideal para estudar! Seu gap de spacing já foi atingido."
    else:
        falta = (proxima_ideal - agora).total_seconds() / 3600
        if falta < 1:
            sugestao = f"⏳ Volte em {int(falta * 60)} minutos para gap ótimo."
        else:
            sugestao = f"⏳ Volte em {falta:.1f}h para gap ótimo de spacing."

    return {
        "gap_horas_min": round(gap_horas_min, 1),
        "gap_horas_max": round(gap_horas_max, 1),
        "horas_desde_ultima": round(horas_desde_ultima, 1) if horas_desde_ultima else None,
        "proxima_sessao_ideal": proxima_ideal.isoformat() if proxima_ideal else None,
        "pronto_para_estudar": ja_passou,
        "dias_ate_prova": dias_prova,
        "sugestao": sugestao,
    }


@router.get(
    "/api/study-intelligence/expressive-writing",
    summary="Expressive Writing — Redução de Ansiedade",
    description="""Verifica se o usuário está a 48h da prova e sugere expressive writing.
Evidência: Ramirez & Beilock (2011) — Escrever sobre medos/preocupações 10min antes
de uma prova melhora desempenho em 5-15%, especialmente para alunos ansiosos.""",
)
def expressive_writing(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Verifica proximidade da prova e sugere expressive writing."""
    from services import get_dias_ate_prova

    dias_prova = get_dias_ate_prova(conn, user_id)

    if not dias_prova or dias_prova > 3:
        return {
            "ativar": False,
            "dias_ate_prova": dias_prova,
            "mensagem": None,
        }

    # Verificar se já fez expressive writing hoje
    ja_fez = (
        conn.execute(
            """
        SELECT COUNT(*) FROM elaboration_log
        WHERE user_id = ? AND prompt_tipo = 'expressive_writing' AND created_at = ?
    """,
            (user_id, today_str()),
        ).fetchone()[0]
        > 0
    )

    if ja_fez:
        return {
            "ativar": False,
            "dias_ate_prova": dias_prova,
            "mensagem": "✅ Você já fez expressive writing hoje. Ótimo!",
        }

    # Prompts baseados na proximidade
    if dias_prova <= 1:
        urgencia = "alta"
        prompt = "Sua prova é AMANHÃ! Escreva por 10 minutos sobre seus medos, preocupações e pensamentos sobre a prova. Não se censure — apenas escreva livremente."
    elif dias_prova <= 2:
        urgencia = "media"
        prompt = "Sua prova é em 2 dias. Reserve 10 minutos para escrever sobre como está se sentindo. Quais medos aparecem? Quais matérias geram insegurança?"
    else:
        urgencia = "baixa"
        prompt = "Sua prova está próxima (3 dias). Comece a processar suas emoções: escreva sobre expectativas, medos e o que pode dar errado."

    return {
        "ativar": True,
        "dias_ate_prova": dias_prova,
        "urgencia": urgencia,
        "prompt": prompt,
        "mensagem": f"✍️ Prova em {dias_prova} dia(s)! Expressive Writing reduz ansiedade em 15% (Ramirez & Beilock, 2011).",
        "instrucoes": [
            "Escreva por 10 minutos sem parar",
            "Não se preocupe com gramática ou coerência",
            "Foque em medos, preocupações e sentimentos sobre a prova",
            "Isso libera espaço na memória de trabalho (working memory)",
        ],
    }


@router.post("/api/study-intelligence/expressive-writing", summary="Salvar Expressive Writing")
def save_expressive_writing(body: dict = Body(...), conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Salva o texto de expressive writing do aluno."""
    texto = body.get("texto", "").strip()
    if not texto:
        raise HTTPException(status_code=400, detail="Texto é obrigatório")

    conn.execute(
        """
        INSERT INTO elaboration_log (user_id, flashcard_id, questao_id, prompt_tipo, resposta_usuario, created_at)
        VALUES (?, NULL, NULL, 'expressive_writing', ?, ?)
    """,
        (user_id, texto, today_str()),
    )
    conn.commit()

    return {
        "ok": True,
        "palavras": len(texto.split()),
        "mensagem": "✅ Expressive writing salvo! Sua ansiedade foi processada. Você vai performar melhor na prova.",
    }

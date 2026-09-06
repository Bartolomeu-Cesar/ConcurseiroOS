"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Depends, Query

from database import get_db_session
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# OVERLEARNING DETECTION — Rohrer & Taylor (2006)
# Revisar itens já dominados é ineficiente (rendimento decrescente)
# ============================================================


@router.get(
    "/api/study-intelligence/overlearning",
    summary="Overlearning Detection",
    description="""Detecta itens que estão sendo revisados desnecessariamente (já dominados).
Baseado em Rohrer & Taylor (2006): após 3+ acertos consecutivos, prática adicional
tem retorno mínimo. O tempo seria melhor investido em itens fracos.""",
)
def overlearning_detection(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Identifica flashcards e questões over-studied e sugere redistribuição do tempo."""

    overlearned_flashcards = []
    overlearned_questoes = []

    # === FLASHCARDS com stability > 60 dias (já consolidados) ===
    # Se stability > 60 e proxima_revisao > hoje + 30 dias: não precisa mais revisar tão cedo
    fc_over = conn.execute(
        """
        SELECT id, pergunta, materia, stability, difficulty, intervalo_dias, proxima_revisao
        FROM flashcards
        WHERE user_id = ? AND stability > 60 AND fsrs_state = 2
        ORDER BY stability DESC
        LIMIT 10
    """,
        (user_id,),
    ).fetchall()
    overlearned_flashcards = [dict(r) for r in fc_over]

    # === QUESTÕES respondidas 5+ vezes TODAS corretas ===
    q_over = conn.execute(
        """
        SELECT q.id, q.enunciado, q.materia,
               COUNT(*) as total_respostas,
               SUM(qr.acertou) as total_acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY qr.questao_id
        HAVING total_respostas >= 5 AND total_acertos = total_respostas
        ORDER BY total_respostas DESC
        LIMIT 10
    """,
        (user_id,),
    ).fetchall()
    overlearned_questoes = [dict(r) for r in q_over]

    # === Matérias com OVER-STUDY (muitas horas + alta taxa acerto) ===
    materias_over = conn.execute(
        """
        SELECT q.materia,
               COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct_acerto,
               COALESCE(SUM(se.horas), 0) as horas_total
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        LEFT JOIN (
            SELECT materia, SUM(horas) as horas
            FROM sessoes_estudo WHERE user_id = ?
            GROUP BY materia
        ) se ON se.materia = q.materia
        WHERE qr.user_id = ?
        GROUP BY q.materia
        HAVING pct_acerto >= 85 AND total >= 20
        ORDER BY pct_acerto DESC
    """,
        (user_id, user_id),
    ).fetchall()

    # Sugerir redistribuição
    # Matérias com MAIS necessidade (baixo acerto, pouco estudo)
    materias_necessitadas = conn.execute(
        """
        SELECT q.materia,
               COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct_acerto
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        HAVING pct_acerto < 60 AND total >= 5
        ORDER BY pct_acerto ASC
        LIMIT 3
    """,
        (user_id,),
    ).fetchall()

    # Calcular tempo desperdiçado (estimativa)
    tempo_potencial_min = len(overlearned_flashcards) * 2 + len(overlearned_questoes) * 3  # ~2min/flash, ~3min/questão

    has_overlearning = bool(overlearned_flashcards or overlearned_questoes or materias_over)

    return {
        "has_overlearning": has_overlearning,
        "overlearned_flashcards": overlearned_flashcards,
        "overlearned_questoes": overlearned_questoes,
        "materias_over_studied": [dict(r) for r in materias_over],
        "materias_necessitadas": [dict(r) for r in materias_necessitadas],
        "tempo_potencial_redistribuir_min": tempo_potencial_min,
        "sugestao": f"Redistribua ~{tempo_potencial_min}min/dia de itens dominados para: {', '.join(r['materia'] for r in materias_necessitadas)}"
        if materias_necessitadas and has_overlearning
        else "Nenhuma redistribuição necessária no momento.",
        "tecnica": "Overlearning (Rohrer & Taylor 2006): após 3+ acertos perfeitos, prática adicional tem retorno decrescente. Invista o tempo em matérias com < 60% de acerto para maximizar ganho marginal.",
    }


# ============================================================
# TRANSFER TESTING — Barnett & Ceci (2002)
# Testar em formato diferente do estudo = transferência mais profunda
# ============================================================


@router.get(
    "/api/study-intelligence/transfer-test",
    summary="Transfer Testing",
    description="""Retorna questões em formato DIFERENTE do que o aluno costuma responder.
Se só respondeu múltipla-escolha, oferece C/E. Se só C/E, oferece aberta.
Baseado em Barnett & Ceci (2002): variar formato força processamento mais profundo.""",
)
def transfer_test(
    materia: str = "",
    quantidade: int = 5,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera teste de transferência: mesmo conteúdo, formato diferente."""

    # Detectar formato predominante das últimas 30 respostas
    ultimas = conn.execute(
        """
        SELECT q.id, q.alternativa_c, q.alternativa_d
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        ORDER BY qr.id DESC LIMIT 30
    """,
        (user_id,),
    ).fetchall()

    # Classificar: se tem alternativa_c = múltipla escolha, senão = C/E
    multipla = sum(1 for r in ultimas if r["alternativa_c"])
    certo_errado = len(ultimas) - multipla

    # Formato preferido vs formato alternativo
    if multipla > certo_errado:
        formato_predominante = "multipla_escolha"
        formato_transferencia = "certo_errado"
        # Buscar questões C/E (sem alternativa_c)
        filtro_formato = "AND (q.alternativa_c IS NULL OR q.alternativa_c = '')"
    else:
        formato_predominante = "certo_errado"
        formato_transferencia = "multipla_escolha"
        filtro_formato = "AND q.alternativa_c IS NOT NULL AND q.alternativa_c != ''"

    # Filtro de matéria
    filtro_materia = ""
    params = [user_id]
    if materia:
        filtro_materia = "AND q.materia = ?"
        params.append(materia)

    # Buscar questões no formato alternativo que o user NUNCA respondeu
    questoes = conn.execute(
        f"""
        SELECT q.id, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c,
               q.alternativa_d, q.alternativa_e, q.resposta_correta, q.materia, q.dificuldade
        FROM questoes q
        WHERE q.user_id = ? {filtro_materia} {filtro_formato}
        AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)
        ORDER BY RANDOM() LIMIT ?
    """,
        params + [user_id, quantidade],
    ).fetchall()

    # Se não tem questões no formato alternativo, pegar questões já respondidas
    # mas apresentar como "geração" (sem alternativas, só enunciado)
    formato_geracao = []
    if len(questoes) < quantidade:
        faltando = quantidade - len(questoes)
        geracoes = conn.execute(
            f"""
            SELECT q.id, q.enunciado, q.resposta_correta, q.materia, q.explicacao
            FROM questoes q
            WHERE q.user_id = ? {filtro_materia}
            AND q.id IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ? AND acertou = 1)
            ORDER BY RANDOM() LIMIT ?
        """,
            params + [user_id, faltando],
        ).fetchall()
        formato_geracao = [dict(r) for r in geracoes]

    return {
        "formato_predominante": formato_predominante,
        "formato_transferencia": formato_transferencia,
        "questoes_formato_alternativo": [dict(q) for q in questoes],
        "questoes_formato_geracao": formato_geracao,
        "total": len(questoes) + len(formato_geracao),
        "mensagem": f"Você costuma responder {formato_predominante.replace('_', ' ')}. Vamos testar transferência com {formato_transferencia.replace('_', ' ')}!",
        "tecnica": "Transfer Testing (Barnett & Ceci 2002): responder no mesmo formato sempre cria 'ilusão de aprendizado'. Variar o formato testa se realmente entendeu o conceito.",
    }


# ============================================================
# PROGRESS MILESTONES — Locke & Latham (2002) Goal-Setting Theory
# Celebrações em marcos de progresso = motivação sustentada
# ============================================================


@router.get(
    "/api/study-intelligence/milestones",
    summary="Progress Milestones",
    description="""Verifica e retorna marcos de progresso alcançados recentemente.
Baseado em Goal-Setting Theory (Locke & Latham 2002): marcos intermediários
com feedback positivo mantêm motivação e senso de progresso.""",
)
def progress_milestones(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna conquistas/marcos alcançados e próximos marcos."""

    milestones_alcancados = []
    proximos_marcos = []

    # === Total de questões respondidas ===
    total_questoes = conn.execute("SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)).fetchone()[0]

    marcos_questoes = [50, 100, 250, 500, 1000, 2500, 5000]
    for marco in marcos_questoes:
        if total_questoes >= marco:
            milestones_alcancados.append(
                {
                    "tipo": "questoes_total",
                    "marco": marco,
                    "atual": total_questoes,
                    "icone": "❓",
                    "titulo": f"{marco} questões respondidas!",
                }
            )
        else:
            proximos_marcos.append(
                {
                    "tipo": "questoes_total",
                    "marco": marco,
                    "atual": total_questoes,
                    "pct": round(total_questoes / marco * 100, 1),
                    "falta": marco - total_questoes,
                    "icone": "❓",
                    "titulo": f"{marco} questões",
                }
            )
            break

    # === Flashcards revisados ===
    total_flash = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    marcos_flash = [50, 100, 300, 500, 1000, 3000]
    for marco in marcos_flash:
        if total_flash >= marco:
            milestones_alcancados.append(
                {
                    "tipo": "flashcards_total",
                    "marco": marco,
                    "atual": total_flash,
                    "icone": "🧠",
                    "titulo": f"{marco} revisões de flashcard!",
                }
            )
        else:
            proximos_marcos.append(
                {
                    "tipo": "flashcards_total",
                    "marco": marco,
                    "atual": total_flash,
                    "pct": round(total_flash / marco * 100, 1),
                    "falta": marco - total_flash,
                    "icone": "🧠",
                    "titulo": f"{marco} revisões",
                }
            )
            break

    # === Matérias dominadas (>80% acerto + 20+ questões) ===
    materias_dominadas = conn.execute(
        """
        SELECT q.materia, COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        HAVING total >= 20 AND pct >= 80
    """,
        (user_id,),
    ).fetchall()

    for m in materias_dominadas:
        milestones_alcancados.append(
            {
                "tipo": "materia_dominada",
                "marco": 80,
                "atual": m["pct"],
                "icone": "🏆",
                "titulo": f"{m['materia']} dominada ({m['pct']}%)!",
                "materia": m["materia"],
            }
        )

    # === Streak máximo ===
    try:
        from utils import get_streak_info

        streak_info = get_streak_info(conn, user_id=user_id)
        streak_atual = streak_info.get("streak_atual", 0)
        streak_max = streak_info.get("streak_maximo", 0)
    except Exception:
        streak_atual = 0
        streak_max = 0

    marcos_streak = [3, 7, 14, 30, 60, 100]
    for marco in marcos_streak:
        if streak_max >= marco:
            milestones_alcancados.append(
                {
                    "tipo": "streak",
                    "marco": marco,
                    "atual": streak_max,
                    "icone": "🔥",
                    "titulo": f"Streak de {marco} dias!",
                }
            )
        else:
            proximos_marcos.append(
                {
                    "tipo": "streak",
                    "marco": marco,
                    "atual": streak_atual,
                    "pct": round(streak_atual / marco * 100, 1),
                    "falta": marco - streak_atual,
                    "icone": "🔥",
                    "titulo": f"Streak de {marco} dias",
                }
            )
            break

    # === Horas totais de estudo ===
    total_horas = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    marcos_horas = [10, 25, 50, 100, 250, 500, 1000]
    for marco in marcos_horas:
        if total_horas >= marco:
            milestones_alcancados.append(
                {
                    "tipo": "horas_total",
                    "marco": marco,
                    "atual": round(total_horas, 1),
                    "icone": "⏱️",
                    "titulo": f"{marco}h de estudo!",
                }
            )
        else:
            proximos_marcos.append(
                {
                    "tipo": "horas_total",
                    "marco": marco,
                    "atual": round(total_horas, 1),
                    "pct": round(total_horas / marco * 100, 1),
                    "falta": round(marco - total_horas, 1),
                    "icone": "⏱️",
                    "titulo": f"{marco}h de estudo",
                }
            )
            break

    # === Progresso do edital ===
    edital_stats = conn.execute(
        """
        SELECT COUNT(*) as total, SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos
        FROM edital WHERE user_id = ? AND arquivado = 0
    """,
        (user_id,),
    ).fetchone()
    if edital_stats["total"] > 0:
        pct_edital = round(edital_stats["concluidos"] / edital_stats["total"] * 100, 1)
        marcos_edital = [25, 50, 75, 100]
        for marco in marcos_edital:
            if pct_edital >= marco:
                milestones_alcancados.append(
                    {
                        "tipo": "edital_progresso",
                        "marco": marco,
                        "atual": pct_edital,
                        "icone": "📋",
                        "titulo": f"Edital {marco}% concluído!",
                    }
                )
            else:
                proximos_marcos.append(
                    {
                        "tipo": "edital_progresso",
                        "marco": marco,
                        "atual": pct_edital,
                        "pct": round(pct_edital / marco * 100, 1),
                        "falta": round(marco - pct_edital, 1),
                        "icone": "📋",
                        "titulo": f"Edital {marco}%",
                    }
                )
                break

    # Próximo marco mais próximo (para destacar)
    proximos_marcos.sort(key=lambda x: -x["pct"])

    return {
        "total_alcancados": len(milestones_alcancados),
        "milestones_alcancados": milestones_alcancados,
        "proximos_marcos": proximos_marcos[:5],  # Top 5 mais próximos
        "mensagem_motivacional": _milestone_message(milestones_alcancados, proximos_marcos),
        "tecnica": "Goal-Setting Theory (Locke & Latham 2002): marcos intermediários com celebração mantêm motivação intrínseca e sensação de progresso contínuo.",
    }


def _milestone_message(alcancados: list, proximos: list) -> str:
    """Gera mensagem motivacional baseada nos marcos."""
    if not alcancados:
        return "🚀 Comece agora! Cada questão te aproxima do primeiro marco."
    if proximos and proximos[0]["pct"] >= 90:
        return f"🔥 Quase lá! Faltam apenas {proximos[0]['falta']} para '{proximos[0]['titulo']}'!"
    total = len(alcancados)
    if total >= 10:
        return "🏆 Incrível! Mais de 10 marcos conquistados. Você está no caminho certo!"
    elif total >= 5:
        return "💪 Excelente progresso! Continue assim, a aprovação está mais perto."
    else:
        return "👏 Bom começo! Cada sessão de estudo constrói a base da sua aprovação."


# ============================================================
# ERROR ANALYSIS PATTERNS — Distractor Analysis + Metacognition
# Categorizar POR QUE erra para atacar a raiz
# ============================================================


@router.get(
    "/api/study-intelligence/error-patterns",
    summary="Error Analysis Patterns",
    description="""Analisa padrões nos erros do usuário e categoriza as causas.
Categorias: interpretação de texto, conceito errado, exceção à regra, pegadinha/distrator, desatenção.
Permite atacar a CAUSA dos erros, não apenas revisar o conteúdo.""",
)
def error_patterns(
    materia: str = "",
    dias: int = 30,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Analisa padrões de erro por matéria nos últimos N dias."""
    data_inicio = (date.today() - timedelta(days=dias)).isoformat()

    # Buscar erros com contexto
    filtro_mat = "AND q.materia = ?" if materia else ""
    params = [user_id, data_inicio]
    if materia:
        params.append(materia)

    erros = conn.execute(
        f"""
        SELECT qr.id as resposta_id, qr.tempo_segundos, qr.confianca,
               q.materia, q.dificuldade, q.enunciado, q.resposta_correta,
               qr.resposta_usuario
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ? AND qr.acertou = 0
        {filtro_mat}
        ORDER BY qr.id DESC
    """,
        params,
    ).fetchall()

    if not erros:
        return {
            "total_erros": 0,
            "padroes": [],
            "distribuicao": {},
            "recomendacoes": ["Sem erros no período analisado. Aumente a dificuldade!"],
        }

    # Classificar erros por padrão provável (heurísticas)
    padroes = {
        "desatencao": [],  # Tempo muito rápido + confiança alta
        "conceito": [],  # Tempo normal + matéria com baixo acerto geral
        "interpretacao": [],  # Tempo alto (leu mas não entendeu)
        "pegadinha": [],  # Tempo normal + confiança alta + errou
        "exceção": [],  # Alternativa próxima da correta
    }

    for e in erros:
        erro = dict(e)
        tempo = erro["tempo_segundos"] or 0
        confianca = erro["confianca"]
        dif = erro["dificuldade"] or "Médio"

        # Threshold de tempo por dificuldade
        tempo_normal = {"Fácil": 30, "Médio": 60, "Difícil": 90}.get(dif, 60)

        # Heurísticas de classificação:
        if tempo > 0 and tempo < tempo_normal * 0.3:
            # Muito rápido = desatenção (não leu direito)
            padroes["desatencao"].append(erro)
        elif tempo > tempo_normal * 1.5:
            # Muito lento = dificuldade de interpretação
            padroes["interpretacao"].append(erro)
        elif confianca is not None and confianca >= 4:
            # Alta confiança mas errou = pegadinha ou exceção
            padroes["pegadinha"].append(erro)
        elif confianca is not None and confianca <= 2:
            # Baixa confiança = sabe que não sabe (conceito)
            padroes["conceito"].append(erro)
        else:
            # Caso geral: conceito ou exceção
            padroes["conceito"].append(erro)

    # Distribuição
    total = len(erros)
    distribuicao = {k: {"count": len(v), "pct": round(len(v) / total * 100, 1)} for k, v in padroes.items() if v}

    # Matérias mais afetadas por cada padrão
    por_materia = {}
    for padrao, lista in padroes.items():
        for e in lista:
            mat = e["materia"]
            if mat not in por_materia:
                por_materia[mat] = {}
            por_materia[mat][padrao] = por_materia[mat].get(padrao, 0) + 1

    # Recomendações baseadas no padrão dominante
    recomendacoes = []
    padrao_dominante = max(padroes, key=lambda k: len(padroes[k])) if erros else None

    if padrao_dominante == "desatencao":
        recomendacoes.append(
            "🎯 Leia TODAS as alternativas antes de responder. Seu erro principal é responder rápido demais."
        )
        recomendacoes.append("⏱️ Espere pelo menos 10s antes de marcar (elimine a pressa).")
    elif padrao_dominante == "interpretacao":
        recomendacoes.append("📖 Foque em interpretação de texto. Sublinhe palavras-chave no enunciado.")
        recomendacoes.append("🔍 Procure por: NÃO, EXCETO, INCORRETA, SEMPRE, NUNCA no enunciado.")
    elif padrao_dominante == "pegadinha":
        recomendacoes.append("⚠️ Cuidado com 'quase certo'. Leia o enunciado 2x quando a resposta parecer óbvia.")
        recomendacoes.append("🧠 Procure a exceção ou condição que invalida a 'resposta óbvia'.")
    elif padrao_dominante == "conceito":
        recomendacoes.append("📚 Revise a teoria antes de fazer mais questões. Há lacunas conceituais.")
        recomendacoes.append("🧠 Use elaboração: POR QUE esta é a resposta? Qual o fundamento?")
    elif padrao_dominante == "exceção":
        recomendacoes.append("📋 Faça uma lista de exceções por matéria. Bancas adoram cobrar exceções.")
        recomendacoes.append("🔄 Crie flashcards específicos para regras + suas exceções.")

    return {
        "total_erros": total,
        "periodo_dias": dias,
        "padrao_dominante": padrao_dominante,
        "distribuicao": distribuicao,
        "por_materia": por_materia,
        "recomendacoes": recomendacoes,
        "detalhes_padroes": {
            "desatencao": {
                "descricao": "Respondeu rápido demais (não leu direito)",
                "count": len(padroes["desatencao"]),
            },
            "conceito": {"descricao": "Não domina o conceito/regra", "count": len(padroes["conceito"])},
            "interpretacao": {
                "descricao": "Dificuldade em interpretar o enunciado",
                "count": len(padroes["interpretacao"]),
            },
            "pegadinha": {
                "descricao": "Caiu em distrator/pegadinha (confiante mas errou)",
                "count": len(padroes["pegadinha"]),
            },
            "exceção": {"descricao": "Não conhecia a exceção à regra", "count": len(padroes["exceção"])},
        },
        "tecnica": "Error Analysis (metacognição + distractor analysis): entender POR QUE erra é mais eficaz que apenas revisar o conteúdo. Atacar a causa elimina categorias inteiras de erro.",
    }


# ============================================================
# MINIMUM EFFECTIVE DOSE — Ericsson (1993) Deliberate Practice
# Tempo ótimo por matéria: não mais que o necessário, não menos
# ============================================================


@router.get(
    "/api/study-intelligence/minimum-dose",
    summary="Minimum Effective Dose",
    description="""Calcula o tempo MÍNIMO necessário por matéria para progredir.
Baseado em Deliberate Practice (Ericsson 1993): qualidade > quantidade.
Matérias com >80% acerto precisam de manutenção (20min/dia).
Matérias com <50% precisam de investimento pesado (1-2h/dia).
Evita overlearning em matérias fortes e subinvestimento em fracas.""",
)
def minimum_effective_dose(
    horas_disponiveis: float = Query(default=3.0, description="Horas disponíveis por dia"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Calcula distribuição ótima do tempo de estudo."""

    # Buscar matérias do ciclo ativo
    ciclo = conn.execute(
        """
        SELECT materia FROM ciclo_estudos WHERE user_id = ? AND ativo = 1 ORDER BY ordem
    """,
        (user_id,),
    ).fetchall()

    if not ciclo:
        return {"materias": [], "mensagem": "Nenhuma matéria no ciclo. Importe do edital."}

    materias_analise = []
    total_minutos = int(horas_disponiveis * 60)

    for c in ciclo:
        mat = c["materia"]

        # Taxa de acerto
        stats = conn.execute(
            """
            SELECT COUNT(*) as total, COALESCE(SUM(acertou), 0) as acertos
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND q.materia = ?
        """,
            (user_id, mat),
        ).fetchone()
        total_q = stats["total"]
        pct_acerto = round(stats["acertos"] / total_q * 100, 1) if total_q > 0 else 0

        # Tópicos pendentes
        topicos = conn.execute(
            """
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status != 'Concluído' THEN 1 ELSE 0 END) as pendentes
            FROM edital WHERE materia = ? AND user_id = ? AND arquivado = 0
        """,
            (mat, user_id),
        ).fetchone()
        pct_concluido = round((topicos["total"] - (topicos["pendentes"] or 0)) / max(topicos["total"], 1) * 100, 1)

        # Flashcards pendentes
        fc_pendentes = conn.execute(
            """
            SELECT COUNT(*) FROM flashcards
            WHERE materia = ? AND user_id = ? AND proxima_revisao <= ?
        """,
            (mat, user_id, today_str()),
        ).fetchone()[0]

        # Questões em erros_revisao
        erros_pendentes = 0
        try:
            erros_pendentes = conn.execute(
                """
                SELECT COUNT(*) FROM erros_revisao er
                JOIN questoes q ON q.id = er.questao_id
                WHERE er.user_id = ? AND q.materia = ? AND er.proxima_revisao <= ?
            """,
                (user_id, mat, today_str()),
            ).fetchone()[0]
        except Exception:
            pass

        # === CALCULAR DOSE MÍNIMA ===
        # Fórmula adaptativa baseada em performance
        if pct_acerto >= 85 and pct_concluido >= 80:
            # Matéria DOMINADA: apenas manutenção
            categoria = "manutencao"
            min_minutos = 15
            max_minutos = 30
            atividade_principal = "Revisão espaçada (flashcards + questões agendadas)"
        elif pct_acerto >= 70:
            # Matéria BOA: reforço leve
            categoria = "reforco"
            min_minutos = 25
            max_minutos = 45
            atividade_principal = "Questões de dificuldade média/difícil + revisão de erros"
        elif pct_acerto >= 50:
            # Matéria MEDIANA: investimento moderado
            categoria = "investimento"
            min_minutos = 40
            max_minutos = 75
            atividade_principal = "Teoria dos tópicos fracos + questões + flashcards novos"
        elif total_q >= 5:
            # Matéria FRACA (com dados): investimento pesado
            categoria = "intensivo"
            min_minutos = 60
            max_minutos = 120
            atividade_principal = "Teoria completa + muitas questões fáceis/médias + flashcards"
        else:
            # Matéria SEM DADOS: investimento inicial
            categoria = "inicial"
            min_minutos = 45
            max_minutos = 90
            atividade_principal = "Estudar teoria + resolver 10-15 questões para calibrar nível"

        # Boost se tem revisões pendentes (FSRS pede revisão HOJE)
        urgencia_boost = 0
        if fc_pendentes > 5:
            urgencia_boost += 10
        if erros_pendentes > 3:
            urgencia_boost += 10

        materias_analise.append(
            {
                "materia": mat,
                "categoria": categoria,
                "min_minutos": min_minutos + urgencia_boost,
                "max_minutos": max_minutos + urgencia_boost,
                "pct_acerto": pct_acerto,
                "pct_concluido": pct_concluido,
                "total_questoes": total_q,
                "fc_pendentes": fc_pendentes,
                "erros_pendentes": erros_pendentes,
                "atividade_principal": atividade_principal,
            }
        )

    # === DISTRIBUIR tempo disponível ===
    # Prioridade: intensivo > investimento > inicial > reforço > manutenção
    prioridade_map = {"intensivo": 5, "inicial": 4, "investimento": 3, "reforco": 2, "manutencao": 1}
    materias_analise.sort(key=lambda m: -prioridade_map.get(m["categoria"], 0))

    # Distribuição proporcional ao peso da prioridade
    total_peso = sum(prioridade_map.get(m["categoria"], 1) for m in materias_analise)
    minutos_restantes = total_minutos

    for m in materias_analise:
        peso = prioridade_map.get(m["categoria"], 1)
        proporcao = peso / total_peso
        minutos_ideais = int(total_minutos * proporcao)
        # Clamp entre min e max
        minutos_alocados = max(m["min_minutos"], min(m["max_minutos"], minutos_ideais))
        # Não exceder o disponível
        minutos_alocados = min(minutos_alocados, minutos_restantes)
        m["minutos_alocados"] = minutos_alocados
        m["horas_alocadas"] = round(minutos_alocados / 60, 1)
        minutos_restantes -= minutos_alocados

    # Se sobrou tempo, distribuir para as mais necessitadas
    if minutos_restantes > 0:
        for m in materias_analise:
            if m["categoria"] in ("intensivo", "investimento", "inicial"):
                extra = min(minutos_restantes, m["max_minutos"] - m["minutos_alocados"])
                m["minutos_alocados"] += extra
                m["horas_alocadas"] = round(m["minutos_alocados"] / 60, 1)
                minutos_restantes -= extra
                if minutos_restantes <= 0:
                    break

    # Resumo
    total_alocado = sum(m["minutos_alocados"] for m in materias_analise)
    eficiencia = round(total_alocado / total_minutos * 100) if total_minutos > 0 else 0

    return {
        "horas_disponiveis": horas_disponiveis,
        "total_minutos_alocados": total_alocado,
        "eficiencia_pct": eficiencia,
        "materias": materias_analise,
        "resumo": {
            "manutencao": len([m for m in materias_analise if m["categoria"] == "manutencao"]),
            "reforco": len([m for m in materias_analise if m["categoria"] == "reforco"]),
            "investimento": len([m for m in materias_analise if m["categoria"] == "investimento"]),
            "intensivo": len([m for m in materias_analise if m["categoria"] == "intensivo"]),
            "inicial": len([m for m in materias_analise if m["categoria"] == "inicial"]),
        },
        "dica": "Foque nos itens 'intensivo' e 'investimento' — são onde você ganha mais pontos na prova com menos tempo.",
        "tecnica": "Minimum Effective Dose (Ericsson 1993): tempo de qualidade > quantidade bruta. Cada matéria tem um ponto ótimo onde mais estudo tem retorno decrescente. Acima de 85% de acerto, mantenha. Abaixo de 50%, invista pesado.",
    }

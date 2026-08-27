"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""
from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Body, Depends, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])

# ============================================================
# GET /api/study-intelligence/pre-test — Quiz antes de estudar
# ============================================================

@router.get("/api/study-intelligence/pre-test", summary="Pre-Testing quiz",
            description="""Retorna questões rápidas sobre um tópico para o aluno responder ANTES de estudá-lo.
Pre-testing melhora retenção em 10-20% mesmo quando o aluno erra todas as questões,
pois ativa curiosidade e direciona a atenção durante o estudo subsequente.""")
def pre_test(
    materia: str,
    topico: str = "",
    quantidade: int = 3,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Gera um pre-test quiz para priming antes do estudo de um tópico."""

    # Buscar questões do banco sobre essa matéria/tópico que o usuário NÃO respondeu ainda
    params = [user_id, materia]
    query = """
        SELECT q.id, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c, q.alternativa_d,
               q.resposta_correta, q.topico, q.materia
        FROM questoes q
        WHERE q.user_id = ? AND q.materia = ?
        AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)
    """
    params.append(user_id)

    if topico:
        query += " AND q.topico = ?"
        params.append(topico)

    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(quantidade)

    questoes = conn.execute(query, params).fetchall()

    # Se não tem questões não-respondidas, pegar aleatórias da matéria (inclusive já respondidas)
    if len(questoes) < quantidade:
        fallback_query = """
            SELECT q.id, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c, q.alternativa_d,
                   q.resposta_correta, q.topico, q.materia
            FROM questoes q
            WHERE q.user_id = ? AND q.materia = ?
        """
        fallback_params = [user_id, materia]
        if topico:
            fallback_query += " AND q.topico = ?"
            fallback_params.append(topico)
        fallback_query += " ORDER BY RANDOM() LIMIT ?"
        fallback_params.append(quantidade)
        questoes = conn.execute(fallback_query, fallback_params).fetchall()

    if not questoes:
        return {
            "disponivel": False,
            "motivo": f"Sem questões de '{materia}' no banco. Adicione questões para ativar Pre-Testing.",
            "questoes": []
        }

    return {
        "disponivel": True,
        "materia": materia,
        "topico": topico or "(geral)",
        "quantidade": len(questoes),
        "instrucao": "Responda sem medo de errar! O objetivo é ativar curiosidade e direcionar sua atenção. Errar aqui MELHORA sua aprendizagem depois.",
        "questoes": [
            {
                "id": q["id"],
                "enunciado": q["enunciado"],
                "alternativas": {
                    "A": q["alternativa_a"],
                    "B": q["alternativa_b"],
                    "C": q["alternativa_c"],
                    "D": q["alternativa_d"],
                },
                "resposta_correta": q["resposta_correta"],
            }
            for q in questoes
        ],
    }


# ============================================================
# POST /api/study-intelligence/self-explanation
# ============================================================

@router.post("/api/study-intelligence/self-explanation", summary="Salvar self-explanation",
             description="Salva a explicação do aluno sobre por que errou uma questão. Técnica de Elaboration.")
def save_self_explanation(
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Salva auto-explicação para uma questão errada."""
    questao_id = body.get("questao_id")
    explicacao = body.get("explicacao", "").strip()

    if not questao_id or not explicacao:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="questao_id e explicacao são obrigatórios")

    # Criar tabela se não existe
    conn.execute("""
        CREATE TABLE IF NOT EXISTS self_explanations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            questao_id INTEGER NOT NULL,
            explicacao TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_self_explanations_user ON self_explanations(user_id)
    """)

    conn.execute(
        "INSERT INTO self_explanations (user_id, questao_id, explicacao, created_at) VALUES (?, ?, ?, ?)",
        (user_id, questao_id, explicacao, today_str())
    )
    conn.commit()

    log.info(f"Self-explanation saved: user={user_id} questao={questao_id} len={len(explicacao)}")
    return {"ok": True, "message": "Explicação salva com sucesso"}


# ============================================================
# GET /api/study-intelligence/calibration — Metacognition calibration data
# ============================================================

@router.get("/api/study-intelligence/calibration", summary="Dados de calibração metacognitiva",
            description="Retorna dados de calibração: confiança vs acerto real ao longo do tempo.")
def get_calibration(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna métricas de calibração metacognitiva.
    
    Calibração perfeita = quando diz 80% confiante, acerta 80% das vezes.
    Overconfidence = confiança > acerto real.
    Underconfidence = confiança < acerto real.
    """
    # Get flashcard review history with FSRS quality (as proxy for accuracy)
    # We use streaks and question responses to build calibration data
    hoje = date.today()
    trinta_dias = (hoje - timedelta(days=30)).isoformat()

    # Question accuracy by day (last 30 days)
    daily_stats = conn.execute("""
        SELECT data, COUNT(*) as total, SUM(acertou) as acertos,
               ROUND(CAST(SUM(acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto
        FROM questoes_respostas
        WHERE user_id = ? AND data >= ?
        GROUP BY data ORDER BY data
    """, (user_id, trinta_dias)).fetchall()

    # Overall calibration metrics
    total_respostas = sum(r["total"] for r in daily_stats) if daily_stats else 0
    total_acertos = sum(r["acertos"] for r in daily_stats) if daily_stats else 0
    accuracy_real = round(total_acertos / total_respostas * 100, 1) if total_respostas > 0 else 0

    # Flashcard quality distribution (proxy for how well user knows material)
    try:
        flash_quality = conn.execute("""
            SELECT easiness_factor, COUNT(*) as cnt
            FROM flashcards
            WHERE user_id = ? AND easiness_factor > 0
            GROUP BY ROUND(easiness_factor, 1)
            ORDER BY easiness_factor
        """, (user_id,)).fetchall()
    except Exception:
        flash_quality = []

    # Improvement trend (comparing first half vs second half of period)
    mid_date = (hoje - timedelta(days=15)).isoformat()
    first_half = [r for r in daily_stats if r["data"] < mid_date]
    second_half = [r for r in daily_stats if r["data"] >= mid_date]

    first_pct = round(sum(r["acertos"] for r in first_half) / max(1, sum(r["total"] for r in first_half)) * 100, 1) if first_half else 0
    second_pct = round(sum(r["acertos"] for r in second_half) / max(1, sum(r["total"] for r in second_half)) * 100, 1) if second_half else 0
    trend = round(second_pct - first_pct, 1)

    return {
        "periodo": f"{trinta_dias} a {hoje.isoformat()}",
        "metricas": {
            "total_respostas": total_respostas,
            "acuracia_real": accuracy_real,
            "tendencia_30d": trend,
            "tendencia_label": "melhorando" if trend > 2 else "estável" if abs(trend) <= 2 else "piorando",
        },
        "diario": [dict(r) for r in daily_stats],
        "flashcard_distribution": [{"ef": r["easiness_factor"], "count": r["cnt"]} for r in flash_quality],
        "dicas": _calibration_tips(accuracy_real, trend),
    }


def _calibration_tips(accuracy: float, trend: float) -> list:
    """Gera dicas personalizadas baseado na calibração."""
    tips = []
    if accuracy < 50:
        tips.append("📉 Acurácia abaixo de 50% — foque em menos matérias por vez e revise os fundamentos")
    elif accuracy < 70:
        tips.append("📊 Acurácia moderada — use o caderno de erros para revisitar questões erradas")
    else:
        tips.append("✅ Boa acurácia! Continue com a revisão espaçada para manter")

    if trend < -5:
        tips.append("⚠️ Tendência de queda — possível sobrecarga. Considere reduzir volume e aumentar qualidade")
    elif trend > 5:
        tips.append("🚀 Tendência de melhora — seu estudo está funcionando! Mantenha o ritmo")

    tips.append("🧠 Dica: use o slider de confiança nos flashcards para calibrar sua metacognição")
    return tips


# ============================================================
# GET /api/study-intelligence/sleep-consolidation
# ============================================================

@router.get("/api/study-intelligence/sleep-consolidation", summary="Sleep consolidation check",
            description="""Verifica se é hora de uma sessão noturna ou revisão matinal.
Estudar antes de dormir + revisar ao acordar = +20% consolidação de memória.""")
def sleep_consolidation(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna recomendações de estudo baseadas no horário (consolidação durante sono)."""
    from datetime import datetime

    now = datetime.now()
    hora = now.hour

    # Determinar período do dia
    if 5 <= hora < 9:
        periodo = "matinal"
    elif 21 <= hora or hora < 1:
        periodo = "noturno"
    else:
        periodo = "diurno"

    # Buscar itens mais importantes para revisão rápida
    hoje = today_str()
    items_revisao = []

    if periodo in ("noturno", "matinal"):
        # Pegar flashcards mais difíceis revisados hoje (para consolidar)
        try:
            # Flashcards com EF baixo (difíceis) que foram revisados recentemente
            dificeis = conn.execute("""
                SELECT id, pergunta, resposta, materia
                FROM flashcards
                WHERE user_id = ? AND easiness_factor < 2.3 AND easiness_factor > 0
                ORDER BY easiness_factor ASC
                LIMIT 5
            """, (user_id,)).fetchall()
            for f in dificeis:
                items_revisao.append({
                    "tipo": "flashcard",
                    "id": f["id"],
                    "pergunta": f["pergunta"],
                    "materia": f["materia"] or "Geral",
                })
        except Exception:
            pass

        # Pegar questões erradas recentes (últimos 3 dias)
        try:
            erros_recentes = conn.execute("""
                SELECT q.id, q.enunciado, q.materia, q.resposta_correta
                FROM questoes_respostas qr
                JOIN questoes q ON q.id = qr.questao_id
                WHERE qr.user_id = ? AND qr.acertou = 0 AND qr.data >= ?
                ORDER BY qr.data DESC
                LIMIT 5
            """, (user_id, (date.today() - timedelta(days=3)).isoformat())).fetchall()
            for e in erros_recentes:
                items_revisao.append({
                    "tipo": "erro_recente",
                    "id": e["id"],
                    "pergunta": e["enunciado"][:100],
                    "materia": e["materia"] or "Geral",
                    "resposta_correta": e["resposta_correta"],
                })
        except Exception:
            pass

    mensagens = {
        "noturno": {
            "titulo": "🌙 Revisão Noturna (Sleep Consolidation)",
            "descricao": "Rever material difícil antes de dormir fortalece a consolidação durante o sono. Revise por 5-10 min sem pressão.",
            "dica": "Não precisa memorizar agora — apenas releia. Seu cérebro fará o trabalho durante a noite.",
        },
        "matinal": {
            "titulo": "☀️ Revisão Matinal (Morning Recall)",
            "descricao": "Tentar lembrar o que estudou ontem à noite ativa retrieval practice após consolidação do sono.",
            "dica": "Tente lembrar ANTES de olhar — o esforço de recuperação é o que fortalece a memória.",
        },
        "diurno": {
            "titulo": "📚 Sessão de Estudo Regular",
            "descricao": "Continue com sua rotina normal. Revisão noturna/matinal será sugerida nos horários ideais.",
            "dica": "Use interleaving: misture matérias diferentes para melhor retenção.",
        },
    }

    return {
        "periodo": periodo,
        "hora_atual": now.strftime("%H:%M"),
        "ativo": periodo in ("noturno", "matinal"),
        **mensagens[periodo],
        "items_revisao": items_revisao[:5],
        "total_items": len(items_revisao),
    }


# ============================================================
# GET /api/study-intelligence/contextual-variation — Mesmo tópico, formatos diferentes
# ============================================================

@router.get("/api/study-intelligence/contextual-variation", summary="Variação contextual",
            description="""Retorna o mesmo tópico em formatos diferentes para melhorar transferência.
Estudar o mesmo conceito como flashcard, questão, dissertativa e explicação oral
melhora a capacidade de aplicar o conhecimento em contextos novos.""")
def contextual_variation(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Gera variações de formato para um mesmo tópico."""
    variations = []

    # 1. Flashcard format (existe?)
    flash_query = "SELECT id, pergunta, resposta FROM flashcards WHERE user_id = ? AND materia = ?"
    flash_params = [user_id, materia]
    if topico:
        flash_query += " AND (pergunta LIKE ? OR resposta LIKE ?)"
        flash_params.extend([f"%{topico}%", f"%{topico}%"])
    flash_query += " ORDER BY RANDOM() LIMIT 2"
    flashcards = conn.execute(flash_query, flash_params).fetchall()
    for f in flashcards:
        variations.append({
            "formato": "flashcard",
            "icone": "🧠",
            "instrucao": "Tente responder mentalmente antes de revelar",
            "conteudo": {"pergunta": f["pergunta"], "resposta": f["resposta"]},
            "id": f["id"],
        })

    # 2. Questão format (existe?)
    q_query = "SELECT id, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, resposta_correta FROM questoes WHERE user_id = ? AND materia = ?"
    q_params = [user_id, materia]
    if topico:
        q_query += " AND topico = ?"
        q_params.append(topico)
    q_query += " ORDER BY RANDOM() LIMIT 2"
    questoes = conn.execute(q_query, q_params).fetchall()
    for q in questoes:
        variations.append({
            "formato": "questao",
            "icone": "❓",
            "instrucao": "Responda a questão objetiva",
            "conteudo": {
                "enunciado": q["enunciado"],
                "alternativas": {"A": q["alternativa_a"], "B": q["alternativa_b"], "C": q["alternativa_c"], "D": q["alternativa_d"]},
                "resposta": q["resposta_correta"],
            },
            "id": q["id"],
        })

    # 3. Dissertativa format (gerado)
    variations.append({
        "formato": "dissertativa",
        "icone": "✍️",
        "instrucao": "Escreva um parágrafo explicando este conceito com suas palavras",
        "conteudo": {
            "prompt": f"Explique com suas palavras o conceito de '{topico or materia}'. Use exemplos práticos.",
            "tempo_sugerido": "3-5 minutos",
        },
        "id": None,
    })

    # 4. Ensinar format (Feynman Technique)
    variations.append({
        "formato": "ensinar",
        "icone": "🎓",
        "instrucao": "Imagine que está ensinando isso a alguém que nunca estudou o tema. Explique em voz alta.",
        "conteudo": {
            "prompt": f"Ensine '{topico or materia}' como se estivesse explicando para um leigo. Se travar, identifique a lacuna.",
            "dica": "Se não conseguir explicar de forma simples, é sinal de que precisa revisar o fundamento.",
        },
        "id": None,
    })

    # 5. Mapa mental (connections)
    variations.append({
        "formato": "conexoes",
        "icone": "🔗",
        "instrucao": "Liste 3 conexões entre este tópico e outros que você já estudou",
        "conteudo": {
            "prompt": f"Como '{topico or materia}' se conecta com outros temas? Liste pelo menos 3 relações.",
            "exemplo": "Ex: 'Direito Penal > Princípio da Legalidade' se conecta com 'Direito Constitucional > Art. 5º' e com 'Direito Administrativo > Legalidade'",
        },
        "id": None,
    })

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "total_variacoes": len(variations),
        "instrucao_geral": "Estudar o mesmo conceito em formatos diferentes melhora a transferência de conhecimento. Complete pelo menos 3 variações.",
        "variacoes": variations,
    }


# ============================================================
# GET /api/study-intelligence/successive-relearning — Ciclos de re-aprendizagem
# ============================================================

@router.get("/api/study-intelligence/successive-relearning", summary="Successive Relearning",
            description="""Identifica tópicos que precisam de ciclos de re-aprendizagem.
Successive Relearning = retrieval practice + spaced repetition em ciclos:
Estudar → Testar → Espaçar → Re-testar → Espaçar mais → Re-testar...
Até atingir critério de domínio (3 acertos consecutivos).""")
def successive_relearning(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna tópicos que estão presos em baixo domínio e precisam de ciclos de re-learning."""
    hoje = date.today()
    trinta_dias = (hoje - timedelta(days=30)).isoformat()

    # Identificar tópicos com "stuck mastery": muitas tentativas mas acurácia não sobe
    stuck_topics = conn.execute("""
        SELECT q.materia, q.topico, COUNT(*) as total_tentativas,
               SUM(qr.acertou) as acertos,
               ROUND(CAST(SUM(qr.acertou) AS REAL) / COUNT(*) * 100, 1) as pct_acerto,
               MAX(qr.data) as ultima_tentativa,
               -- Calcular se os últimos 3 acertos foram consecutivos
               (SELECT COUNT(*) FROM (
                   SELECT acertou FROM questoes_respostas
                   WHERE questao_id IN (SELECT id FROM questoes WHERE materia = q.materia AND topico = q.topico AND user_id = ?)
                   AND user_id = ?
                   ORDER BY data DESC, id DESC LIMIT 3
               ) sub WHERE acertou = 1) as ultimos_3_acertos
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ?
        GROUP BY q.materia, q.topico
        HAVING total_tentativas >= 4 AND pct_acerto < 70
        ORDER BY pct_acerto ASC
    """, (user_id, user_id, user_id, trinta_dias)).fetchall()

    cycles = []
    for t in stuck_topics:
        # Determine cycle stage
        acerto_pct = t["pct_acerto"]
        ultimos_3 = t["ultimos_3_acertos"] or 0
        total = t["total_tentativas"]

        if ultimos_3 >= 3:
            status = "dominado"
            proxima_acao = "Manter revisão espaçada normal"
            cor = "green"
        elif acerto_pct < 40:
            status = "re-estudar"
            proxima_acao = "Voltar ao material base. Releia e faça anotações antes de testar novamente."
            cor = "red"
        elif acerto_pct < 60:
            status = "praticar"
            proxima_acao = "Resolver mais questões variadas deste tópico. Foque na self-explanation."
            cor = "peach"
        else:
            status = "consolidar"
            proxima_acao = "Quase lá! Faça um teste final em 2-3 dias para fixar."
            cor = "yellow"

        days_since = 0
        try:
            days_since = (hoje - date.fromisoformat(t["ultima_tentativa"])).days
        except (ValueError, TypeError):
            pass

        cycles.append({
            "materia": t["materia"],
            "topico": t["topico"] or "(geral)",
            "status": status,
            "cor": cor,
            "pct_acerto": acerto_pct,
            "total_tentativas": total,
            "ultimos_3_acertos": ultimos_3,
            "dias_desde_ultima": days_since,
            "proxima_acao": proxima_acao,
            # Cycle info
            "ciclo_atual": 1 if acerto_pct < 40 else 2 if acerto_pct < 60 else 3,
            "ciclos_necessarios": 3,
            "criterio_dominio": "3 acertos consecutivos",
        })

    # Summary
    total_stuck = len(cycles)
    em_reestudo = len([c for c in cycles if c["status"] == "re-estudar"])
    em_pratica = len([c for c in cycles if c["status"] == "praticar"])
    em_consolidacao = len([c for c in cycles if c["status"] == "consolidar"])

    return {
        "total_topicos_stuck": total_stuck,
        "resumo": {
            "re_estudar": em_reestudo,
            "praticar": em_pratica,
            "consolidar": em_consolidacao,
        },
        "instrucao": "Successive Relearning: Para cada tópico abaixo, siga o ciclo Estudar → Testar → Espaçar → Re-testar até atingir 3 acertos consecutivos.",
        "ciclos": cycles[:15],
    }


# ============================================================
# GET /api/study-intelligence/dual-coding — Texto + Visual
# ============================================================

@router.get("/api/study-intelligence/dual-coding", summary="Dual Coding suggestions",
            description="""Sugere representações visuais para tópicos estudados.
Dual Coding: combinar informação verbal (texto) + visual (diagrama/imagem) cria 2 caminhos
independentes de memória, dobrando as chances de recall.""")
def dual_coding(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna sugestões de representação visual para um tópico."""

    # Templates de visualização por tipo de conteúdo
    visual_templates = {
        "processo": {
            "tipo": "fluxograma",
            "icone": "🔄",
            "instrucao": "Desenhe um fluxograma com as etapas em sequência. Use setas para indicar a ordem.",
            "exemplo": "Início → Petição → Citação → Contestação → Instrução → Sentença → Recurso",
        },
        "comparacao": {
            "tipo": "tabela_comparativa",
            "icone": "⚖️",
            "instrucao": "Crie uma tabela lado-a-lado comparando os conceitos similares.",
            "exemplo": "| Aspecto | Conceito A | Conceito B |\n|---------|-----------|------------|",
        },
        "hierarquia": {
            "tipo": "mapa_mental",
            "icone": "🌳",
            "instrucao": "Desenhe um mapa mental com o conceito central e ramificações.",
            "exemplo": "Tema central no meio → Subtemas em galhos → Detalhes nas folhas",
        },
        "timeline": {
            "tipo": "linha_do_tempo",
            "icone": "📅",
            "instrucao": "Organize os eventos/fatos em uma linha do tempo cronológica.",
            "exemplo": "1988 → CF | 1990 → CDC | 2002 → CC | 2015 → CPC",
        },
        "causa_efeito": {
            "tipo": "diagrama_causa_efeito",
            "icone": "🔀",
            "instrucao": "Desenhe causas à esquerda, efeitos à direita, conectados por setas.",
            "exemplo": "Causa 1 →\nCausa 2 → [Evento] → Consequência\nCausa 3 →",
        },
        "acronimo": {
            "tipo": "mnemônico_visual",
            "icone": "🎨",
            "instrucao": "Crie um acrônimo ou imagem mental associativa para memorizar a lista.",
            "exemplo": "LIMPE = Legalidade, Impessoalidade, Moralidade, Publicidade, Eficiência",
        },
    }

    # Detectar tipo de conteúdo baseado na matéria/tópico
    topico_lower = (topico or materia).lower()
    suggested_type = "hierarquia"  # default
    if any(w in topico_lower for w in ["processo", "procedimento", "fase", "etapa", "rito"]):
        suggested_type = "processo"
    elif any(w in topico_lower for w in ["diferença", "comparar", "versus", "vs", "distinção"]):
        suggested_type = "comparacao"
    elif any(w in topico_lower for w in ["história", "evolução", "cronolog", "constitui"]):
        suggested_type = "timeline"
    elif any(w in topico_lower for w in ["causa", "consequência", "efeito", "resultado"]):
        suggested_type = "causa_efeito"
    elif any(w in topico_lower for w in ["princípio", "requisito", "elemento", "espécie", "tipo", "modalidade"]):
        suggested_type = "acronimo"

    primary = visual_templates[suggested_type]

    # Buscar flashcards do tópico para sugerir o que visualizar
    content_items = []
    try:
        cards = conn.execute(
            "SELECT pergunta, resposta FROM flashcards WHERE user_id = ? AND materia = ? LIMIT 5",
            (user_id, materia)
        ).fetchall()
        content_items = [{"q": c["pergunta"], "a": c["resposta"]} for c in cards]
    except Exception:
        pass

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "sugestao_principal": {
            **primary,
            "materia": materia,
            "topico": topico,
        },
        "todas_opcoes": [
            {"tipo": v["tipo"], "icone": v["icone"], "instrucao": v["instrucao"]}
            for v in visual_templates.values()
        ],
        "conteudo_para_visualizar": content_items,
        "dica_geral": "Não precisa ser bonito! Um rabisco simples no papel ou um diagrama rápido já ativa o canal visual da memória. O importante é CRIAR, não copiar.",
    }


# ============================================================
# GET /api/study-intelligence/concrete-examples — Exemplos concretos
# ============================================================

@router.get("/api/study-intelligence/concrete-examples", summary="Concrete examples",
            description="""Gera exemplos concretos e analogias do mundo real para conceitos abstratos.
Exemplos concretos ancoram conceitos abstratos na memória de longo prazo.""")
def concrete_examples(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Retorna exemplos concretos para um tópico (gerados por templates ou IA)."""

    # Base de exemplos por matéria (templates comuns para concursos)
    exemplos_base = {
        "Direito Constitucional": [
            {"conceito": "Princípio da Legalidade", "exemplo": "Um servidor público só pode fazer o que a lei autoriza. Se não há lei permitindo, está proibido. É como um cardápio: só pode pedir o que está escrito."},
            {"conceito": "Habeas Corpus", "exemplo": "João foi preso sem mandado e sem flagrante. Ele pode pedir HC para ser solto imediatamente — é como um 'botão de emergência' contra prisão ilegal."},
            {"conceito": "Cláusula Pétrea", "exemplo": "Imagine a Constituição como uma casa. As cláusulas pétreas são as vigas de sustentação — você pode reformar paredes (emendar), mas nunca mexer nas vigas."},
        ],
        "Direito Penal": [
            {"conceito": "Dolo Eventual", "exemplo": "Motorista bêbado: 'sei que posso matar alguém, mas tanto faz, vou dirigir assim mesmo'. Ele não QUER matar, mas ACEITA o risco."},
            {"conceito": "Culpa Consciente", "exemplo": "Malabarista com facas: 'sei que posso machucar alguém, mas confio na minha habilidade'. Ele prevê o risco mas acredita sinceramente que não vai acontecer."},
            {"conceito": "Legítima Defesa", "exemplo": "Ladrão armado invade sua casa. Você o empurra e ele cai. Usou força proporcional contra agressão injusta e atual — legítima defesa perfeita."},
        ],
        "Direito Administrativo": [
            {"conceito": "Impessoalidade", "exemplo": "Prefeito inaugura obra com placa 'Obra do Prefeito Silva'. ERRADO — a obra é do município, não da pessoa. É como um funcionário de banco: age em nome do banco, não dele."},
            {"conceito": "Discricionariedade", "exemplo": "Lei diz: 'prefeitura PODE construir praça'. O prefeito decide onde e quando. Mas se a lei diz 'DEVE construir', não tem escolha."},
        ],
    }

    # Buscar exemplos da base
    examples = exemplos_base.get(materia, [])

    # Se tem tópico específico, filtrar
    if topico and examples:
        filtered = [e for e in examples if topico.lower() in e["conceito"].lower()]
        if filtered:
            examples = filtered

    # Template para o aluno criar seus próprios exemplos
    create_template = {
        "instrucao": "Crie seu próprio exemplo concreto! Exemplos pessoais são mais memoráveis.",
        "formula": "Conceito abstrato → Situação do dia-a-dia que ilustra o conceito",
        "dicas": [
            "Use situações que você já viveu ou presenciou",
            "Quanto mais absurdo/engraçado, mais memorável",
            "Relacione com personagens de séries/filmes que você conhece",
            "Imagine explicando para uma criança de 10 anos",
        ],
    }

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "exemplos_prontos": examples[:5],
        "total_exemplos": len(examples),
        "criar_proprio": create_template,
        "por_que_funciona": "Exemplos concretos ativam mais áreas cerebrais que definições abstratas. Seu cérebro 'simula' a situação, criando memória episódica + semântica simultaneamente.",
    }


# ============================================================
# GET /api/study-intelligence/memory-palace — Palácio da Memória
# ============================================================

@router.get("/api/study-intelligence/memory-palace", summary="Memory Palace / Method of Loci",
            description="""Guia para criar um Palácio da Memória para listas e sequências.
O Method of Loci (Palácio da Memória) usa memória espacial para ancorar informações.
Ideal para: artigos de lei, princípios, listas de requisitos, prazos.""")
def memory_palace(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Guia para construir um Palácio da Memória para o tópico."""

    # Buscar items que são "listas" (princípios, requisitos, etc.)
    items_to_memorize = []
    try:
        # Flashcards dessa matéria que parecem ser listas
        cards = conn.execute("""
            SELECT pergunta, resposta FROM flashcards
            WHERE user_id = ? AND materia = ?
            AND (resposta LIKE '%,%,%' OR resposta LIKE '%1)%' OR resposta LIKE '%•%'
                 OR pergunta LIKE '%quais%' OR pergunta LIKE '%requisitos%'
                 OR pergunta LIKE '%princípios%' OR pergunta LIKE '%elementos%')
            LIMIT 5
        """, (user_id, materia)).fetchall()
        items_to_memorize = [{"pergunta": c["pergunta"], "resposta": c["resposta"]} for c in cards]
    except Exception:
        pass

    # Palácio template
    palace_template = {
        "nome": "Sua Casa",
        "locais": [
            {"posicao": 1, "local": "🚪 Porta de entrada", "dica": "Primeiro item da lista — visualize algo enorme bloqueando a porta"},
            {"posicao": 2, "local": "🛋️ Sala / Sofá", "dica": "Segundo item — imagine sentado no sofá fazendo algo absurdo"},
            {"posicao": 3, "local": "📺 TV / Estante", "dica": "Terceiro item — a TV está mostrando algo relacionado"},
            {"posicao": 4, "local": "🍳 Cozinha / Geladeira", "dica": "Quarto item — está dentro da geladeira, congelado"},
            {"posicao": 5, "local": "🚿 Banheiro", "dica": "Quinto item — visualize no espelho do banheiro"},
            {"posicao": 6, "local": "🛏️ Quarto / Cama", "dica": "Sexto item — está deitado na sua cama"},
            {"posicao": 7, "local": "🪟 Janela", "dica": "Sétimo item — está pendurado na janela"},
            {"posicao": 8, "local": "🚗 Garagem / Carro", "dica": "Oitavo item — está no banco do motorista"},
        ],
        "dicas_criacao": [
            "Use imagens ABSURDAS e EXAGERADAS (quanto mais ridículo, mais memorável)",
            "Ative os 5 sentidos: veja, ouça, sinta cheiro, toque, prove",
            "Faça os objetos interagirem com o local (não apenas 'colocados' lá)",
            "Percorra o palácio SEMPRE na mesma ordem",
            "Revise o percurso 3x: imediatamente, em 1h, e antes de dormir",
        ],
    }

    # Exemplo prático com conteúdo jurídico
    exemplo = {
        "topico": "Princípios da Administração Pública (LIMPE)",
        "palacio": [
            {"local": "Porta", "item": "Legalidade", "imagem": "Um juiz GIGANTE bloqueia a porta com um livro de leis. Você SÓ passa se mostrar a lei autorizando."},
            {"local": "Sala", "item": "Impessoalidade", "imagem": "Todas as pessoas no sofá estão sem rosto — são idênticas, impessoais."},
            {"local": "Cozinha", "item": "Moralidade", "imagem": "Sua avó está na cozinha olhando feio — ela julga se suas ações são morais."},
            {"local": "Banheiro", "item": "Publicidade", "imagem": "O espelho do banheiro é na verdade uma TV transmitindo tudo ao vivo para o público."},
            {"local": "Quarto", "item": "Eficiência", "imagem": "Um robô super-eficiente está arrumando seu quarto em 2 segundos."},
        ],
    }

    return {
        "materia": materia,
        "topico": topico or "(geral)",
        "palace_template": palace_template,
        "exemplo_pratico": exemplo,
        "items_para_memorizar": items_to_memorize,
        "ideal_para": [
            "Listas de princípios (LIMPE, contraditório, etc.)",
            "Artigos de lei e incisos",
            "Prazos processuais",
            "Requisitos de validade",
            "Sequências de fases/etapas",
        ],
        "ciencia": "O Method of Loci ativa o hipocampo (memória espacial + episódica). Campeões de memória usam esta técnica para memorizar 500+ dígitos em 5 minutos.",
    }


# ============================================================
# GET /api/study-intelligence/overconfidence — Confidence-Based Repetition (A2)
# ============================================================

@router.get("/api/study-intelligence/overconfidence", summary="Análise de overconfidence",
            description="""Identifica matérias onde o aluno tem ilusão de saber:
alta confiança mas baixo acerto. Overconfidence index > 20 = 'ilusão de saber'.""")
def overconfidence_analysis(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Calcula overconfidence por matéria: avg_confianca/3*100 - pct_acerto."""
    rows = conn.execute("""
        SELECT q.materia,
               COUNT(qr.id) as total_respostas,
               SUM(qr.acertou) as acertos,
               AVG(qr.confianca) as avg_confianca
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.confianca IS NOT NULL
        GROUP BY q.materia
        HAVING COUNT(qr.id) >= 5
        ORDER BY AVG(qr.confianca) DESC
    """, (user_id,)).fetchall()

    materias = []
    for r in rows:
        total = r["total_respostas"]
        acertos = r["acertos"] or 0
        avg_conf = r["avg_confianca"] or 0
        pct_acerto = round(acertos / total * 100, 1) if total > 0 else 0
        confianca_pct = round(avg_conf / 3 * 100, 1)
        overconfidence_idx = round(confianca_pct - pct_acerto, 1)

        status = "ilusão de saber" if overconfidence_idx > 20 else (
            "calibrado" if abs(overconfidence_idx) <= 10 else (
                "subconfiante" if overconfidence_idx < -10 else "leve overconfidence"
            )
        )

        sugestoes = []
        if overconfidence_idx > 20:
            sugestoes = [
                f"⚠️ Você marca alta confiança em {r['materia']} mas acerta apenas {pct_acerto}%",
                "📖 Revise os fundamentos desta matéria antes de avançar",
                "🔄 Use flashcards com revisão espaçada para consolidar",
                "❓ Resolva mais questões desta matéria com feedback detalhado",
            ]
        elif overconfidence_idx > 10:
            sugestoes = [
                f"📊 Confiança levemente acima do desempenho real em {r['materia']}",
                "🧪 Faça um mini-simulado focado nesta matéria para calibrar",
            ]
        elif overconfidence_idx < -10:
            sugestoes = [
                f"💪 Você sabe mais do que pensa em {r['materia']}! Acurácia: {pct_acerto}%",
                "🎯 Aumente a dificuldade — você está pronto para questões mais difíceis",
            ]

        materias.append({
            "materia": r["materia"],
            "total_respostas": total,
            "pct_acerto": pct_acerto,
            "avg_confianca": round(avg_conf, 2),
            "confianca_pct": confianca_pct,
            "overconfidence_idx": overconfidence_idx,
            "status": status,
            "sugestoes": sugestoes,
        })

    # Ordenar por maior overconfidence (top 5)
    materias.sort(key=lambda x: x["overconfidence_idx"], reverse=True)
    top5 = materias[:5]

    ilusoes = [m for m in materias if m["status"] == "ilusão de saber"]

    return {
        "total_materias_analisadas": len(materias),
        "ilusoes_de_saber": len(ilusoes),
        "alerta_geral": (
            f"🚨 Você tem {len(ilusoes)} matéria(s) com 'ilusão de saber' — priorize revisão!"
            if ilusoes else "✅ Sua autoavaliação está bem calibrada."
        ),
        "top5_overconfidence": top5,
        "todas_materias": materias,
        "dica_metodologica": "Marque sua confiança (1-3) ao responder questões para melhorar a calibração metacognitiva.",
    }


# ============================================================
# POST /api/study-intelligence/elaboration — Salvar elaboração (A3)
# ============================================================

@router.post("/api/study-intelligence/elaboration", summary="Salvar elaboration log",
             description="Registra a resposta do aluno a um prompt elaborativo.")
def save_elaboration(
    body: dict,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id)
):
    """Grava na tabela elaboration_log.
    body: {flashcard_id ou questao_id, prompt_tipo, resposta_usuario}
    """
    flashcard_id = body.get("flashcard_id")
    questao_id = body.get("questao_id")
    prompt_tipo = body.get("prompt_tipo", "")
    resposta_usuario = body.get("resposta_usuario", "")

    if not prompt_tipo:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="prompt_tipo é obrigatório")

    conn.execute("""
        INSERT INTO elaboration_log (user_id, flashcard_id, questao_id, prompt_tipo, resposta_usuario, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, flashcard_id, questao_id, prompt_tipo, resposta_usuario, today_str()))
    conn.commit()

    return {"ok": True, "message": "Elaboração registrada com sucesso"}


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
    rows = conn.execute("""
        SELECT data, horas_estudadas FROM streaks
        WHERE data >= ? AND user_id = ?
        ORDER BY data DESC
    """, (sete_dias_atras, user_id)).fetchall()

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
        sugestao = "Sua carga de estudo está elevada. Intercale dias mais leves para otimizar a consolidação de memória."

    return {
        "risk": risk,
        "dias_overwork": max(dias_overwork_150, dias_overwork_200),
        "media_horas_7d": media_horas_7d,
        "meta_horas": meta_horas,
        "sugestao": sugestao,
    }


@router.get("/api/study-intelligence/burnout", summary="Burnout Detection",
            description="Detecta risco de esgotamento baseado em padrão de horas de estudo vs meta configurada.")
def burnout_detection(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna análise de risco de burnout baseado nos últimos 7 dias."""
    return _detect_burnout(conn, user_id)



# ============================================================
# BLOCKED PRACTICE DETECTION — Rohrer (2012)
# Interleaving produz +20-40% retenção vs prática em bloco
# ============================================================

@router.get("/api/study-intelligence/blocked-practice", summary="Blocked Practice Detection",
            description="""Detecta quando o usuário está estudando em bloco (mesma matéria por muito tempo)
e sugere intercalar. Interleaving produz 20-40% mais retenção que blocked practice (Rohrer 2012).""")
def blocked_practice_detection(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Analisa sessão atual e retorna alerta se detectar prática em bloco."""
    hoje = today_str()

    # Verificar últimas 15 respostas de questões de hoje
    ultimas = conn.execute("""
        SELECT q.materia, qr.data, qr.id
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data = ?
        ORDER BY qr.id DESC LIMIT 15
    """, (user_id, hoje)).fetchall()

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
    sessao_mesma = conn.execute("""
        SELECT SUM(horas) as total FROM sessoes_estudo
        WHERE user_id = ? AND data = ? AND materia = ?
    """, (user_id, hoje, current_materia)).fetchone()
    horas_mesma = sessao_mesma["total"] or 0

    # Alertar se: 8+ questões seguidas da mesma matéria OU 1.5h+ da mesma matéria hoje
    is_blocked = streak >= 8 or horas_mesma >= 1.5

    # Sugerir matéria diferente para intercalar
    sugestao_materia = None
    if is_blocked:
        # Buscar matéria menos estudada hoje
        outras = conn.execute("""
            SELECT DISTINCT materia FROM edital
            WHERE user_id = ? AND materia != ? AND arquivado = 0
            AND materia NOT IN (
                SELECT DISTINCT q.materia FROM questoes_respostas qr
                JOIN questoes q ON q.id = qr.questao_id
                WHERE qr.user_id = ? AND qr.data = ?
                AND qr.id > (SELECT MAX(id) - 5 FROM questoes_respostas WHERE user_id = ? AND data = ?)
            )
            ORDER BY RANDOM() LIMIT 1
        """, (user_id, current_materia, user_id, hoje, user_id, hoje)).fetchone()
        if outras:
            sugestao_materia = outras["materia"]
        else:
            # Qualquer outra matéria do ciclo
            outra = conn.execute("""
                SELECT materia FROM ciclo_estudos
                WHERE user_id = ? AND ativo = 1 AND materia != ?
                ORDER BY horas_cumpridas / horas_alvo ASC LIMIT 1
            """, (user_id, current_materia)).fetchone()
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

@router.get("/api/study-intelligence/sleep-consolidation", summary="Sleep Consolidation Review",
            description="""Retorna itens ideais para revisão pré-sono (21h-1h) e matinal (5h-9h).
Baseado em Born & Wilhelm (2012): memórias são consolidadas durante o sono.
Revisar material difícil antes de dormir e re-testar ao acordar melhora retenção em ~20%.""")
def sleep_consolidation(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna flashcards e questões para revisão de consolidação."""
    from datetime import datetime
    hora_atual = datetime.now().hour
    hoje = today_str()
    ontem = (date.today() - timedelta(days=1)).isoformat()

    # Determinar modo: noturno (21h-1h) ou matinal (5h-9h)
    if 21 <= hora_atual or hora_atual <= 1:
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
        fc_errados = conn.execute("""
            SELECT f.id, f.pergunta, f.resposta, f.materia, f.stability, f.difficulty
            FROM flashcards f
            WHERE f.user_id = ? AND f.difficulty > 5
            AND f.id IN (
                SELECT id FROM flashcards WHERE user_id = ? AND proxima_revisao = ?
            )
            ORDER BY f.difficulty DESC
            LIMIT 5
        """, (user_id, user_id, (date.today() + timedelta(days=1)).isoformat())).fetchall()
        flashcards_consolidacao.extend([dict(r) for r in fc_errados])

        # 2. Flashcards novos vistos hoje (stability baixa = frágil)
        fc_frageis = conn.execute("""
            SELECT id, pergunta, resposta, materia, stability, difficulty
            FROM flashcards
            WHERE user_id = ? AND stability > 0 AND stability <= 3
            AND proxima_revisao > ?
            ORDER BY stability ASC
            LIMIT 5
        """, (user_id, hoje)).fetchall()
        for r in fc_frageis:
            if r["id"] not in {f["id"] for f in flashcards_consolidacao}:
                flashcards_consolidacao.append(dict(r))

    elif modo == "matinal":
        # Matinal: re-testar os mesmos itens da noite anterior (ou erros de ontem)
        # Cards com próxima revisão = hoje (normal FSRS) + erros de ontem
        fc_hoje = conn.execute("""
            SELECT id, pergunta, resposta, materia, stability, difficulty
            FROM flashcards
            WHERE user_id = ? AND proxima_revisao <= ?
            ORDER BY difficulty DESC, stability ASC
            LIMIT 8
        """, (user_id, hoje)).fetchall()
        flashcards_consolidacao = [dict(r) for r in fc_hoje]

    # === QUESTÕES para consolidação ===
    questoes_consolidacao = []

    if modo == "noturno":
        # Questões erradas hoje
        q_erradas = conn.execute("""
            SELECT q.id, q.enunciado, q.materia, q.resposta_correta, q.explicacao
            FROM questoes q
            JOIN questoes_respostas qr ON qr.questao_id = q.id
            WHERE qr.user_id = ? AND qr.data = ? AND qr.acertou = 0
            ORDER BY qr.id DESC
            LIMIT 5
        """, (user_id, hoje)).fetchall()
        questoes_consolidacao = [dict(r) for r in q_erradas]

    elif modo == "matinal":
        # Questões erradas ontem (re-testar após consolidação do sono)
        q_ontem = conn.execute("""
            SELECT q.id, q.enunciado, q.materia, q.resposta_correta, q.explicacao
            FROM questoes q
            JOIN questoes_respostas qr ON qr.questao_id = q.id
            WHERE qr.user_id = ? AND qr.data = ? AND qr.acertou = 0
            ORDER BY RANDOM()
            LIMIT 5
        """, (user_id, ontem)).fetchall()
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
        "dica": "Não estude conteúdo NOVO antes de dormir — apenas REVISE o que já viu hoje." if modo == "noturno" else "Tente recordar ANTES de olhar a resposta (retrieval practice)." if modo == "matinal" else "",
    }


# ============================================================
# OVERLEARNING DETECTION — Rohrer & Taylor (2006)
# Revisar itens já dominados é ineficiente (rendimento decrescente)
# ============================================================

@router.get("/api/study-intelligence/overlearning", summary="Overlearning Detection",
            description="""Detecta itens que estão sendo revisados desnecessariamente (já dominados).
Baseado em Rohrer & Taylor (2006): após 3+ acertos consecutivos, prática adicional
tem retorno mínimo. O tempo seria melhor investido em itens fracos.""")
def overlearning_detection(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Identifica flashcards e questões over-studied e sugere redistribuição do tempo."""

    overlearned_flashcards = []
    overlearned_questoes = []
    hoje = today_str()

    # === FLASHCARDS com stability > 60 dias (já consolidados) ===
    # Se stability > 60 e proxima_revisao > hoje + 30 dias: não precisa mais revisar tão cedo
    fc_over = conn.execute("""
        SELECT id, pergunta, materia, stability, difficulty, intervalo_dias, proxima_revisao
        FROM flashcards
        WHERE user_id = ? AND stability > 60 AND fsrs_state = 2
        ORDER BY stability DESC
        LIMIT 10
    """, (user_id,)).fetchall()
    overlearned_flashcards = [dict(r) for r in fc_over]

    # === QUESTÕES respondidas 5+ vezes TODAS corretas ===
    q_over = conn.execute("""
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
    """, (user_id,)).fetchall()
    overlearned_questoes = [dict(r) for r in q_over]

    # === Matérias com OVER-STUDY (muitas horas + alta taxa acerto) ===
    materias_over = conn.execute("""
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
    """, (user_id, user_id)).fetchall()

    # Sugerir redistribuição
    # Matérias com MAIS necessidade (baixo acerto, pouco estudo)
    materias_necessitadas = conn.execute("""
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
    """, (user_id,)).fetchall()

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
        "sugestao": f"Redistribua ~{tempo_potencial_min}min/dia de itens dominados para: {', '.join(r['materia'] for r in materias_necessitadas)}" if materias_necessitadas and has_overlearning else "Nenhuma redistribuição necessária no momento.",
        "tecnica": "Overlearning (Rohrer & Taylor 2006): após 3+ acertos perfeitos, prática adicional tem retorno decrescente. Invista o tempo em matérias com < 60% de acerto para maximizar ganho marginal.",
    }


# ============================================================
# TRANSFER TESTING — Barnett & Ceci (2002)
# Testar em formato diferente do estudo = transferência mais profunda
# ============================================================

@router.get("/api/study-intelligence/transfer-test", summary="Transfer Testing",
            description="""Retorna questões em formato DIFERENTE do que o aluno costuma responder.
Se só respondeu múltipla-escolha, oferece C/E. Se só C/E, oferece aberta.
Baseado em Barnett & Ceci (2002): variar formato força processamento mais profundo.""")
def transfer_test(
    materia: str = "",
    quantidade: int = 5,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera teste de transferência: mesmo conteúdo, formato diferente."""
    hoje = today_str()

    # Detectar formato predominante das últimas 30 respostas
    ultimas = conn.execute("""
        SELECT q.id, q.alternativa_c, q.alternativa_d
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        ORDER BY qr.id DESC LIMIT 30
    """, (user_id,)).fetchall()

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
    questoes = conn.execute(f"""
        SELECT q.id, q.enunciado, q.alternativa_a, q.alternativa_b, q.alternativa_c,
               q.alternativa_d, q.alternativa_e, q.resposta_correta, q.materia, q.dificuldade
        FROM questoes q
        WHERE q.user_id = ? {filtro_materia} {filtro_formato}
        AND q.id NOT IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)
        ORDER BY RANDOM() LIMIT ?
    """, params + [user_id, quantidade]).fetchall()

    # Se não tem questões no formato alternativo, pegar questões já respondidas
    # mas apresentar como "geração" (sem alternativas, só enunciado)
    formato_geracao = []
    if len(questoes) < quantidade:
        faltando = quantidade - len(questoes)
        geracoes = conn.execute(f"""
            SELECT q.id, q.enunciado, q.resposta_correta, q.materia, q.explicacao
            FROM questoes q
            WHERE q.user_id = ? {filtro_materia}
            AND q.id IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ? AND acertou = 1)
            ORDER BY RANDOM() LIMIT ?
        """, params + [user_id, faltando]).fetchall()
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
# ADAPTIVE BREAK SCHEDULING — Ultradian Rhythms + Fatigue Detection
# Pausas inteligentes baseadas em fadiga real, não timer fixo
# ============================================================

@router.get("/api/study-intelligence/adaptive-break", summary="Adaptive Break Scheduling",
            description="""Calcula o momento ideal para pausa baseado em fadiga real:
tempo de resposta crescente + taxa de acerto decrescente + duração da sessão.
Baseado em ritmos ultradianos (~90min) e detecção de fadiga cognitiva.""")
def adaptive_break(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Analisa sessão atual e recomenda se deve pausar ou continuar."""
    hoje = today_str()

    # Últimas 20 respostas de hoje com tempo
    respostas = conn.execute("""
        SELECT qr.acertou, qr.tempo_segundos, qr.id
        FROM questoes_respostas qr
        WHERE qr.user_id = ? AND qr.data = ? AND qr.tempo_segundos > 0
        ORDER BY qr.id ASC
    """, (user_id, hoje)).fetchall()

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
    tempo_ultimas5 = sum(r["tempo_segundos"] for r in ultimas5) / 5
    acerto_ultimas5 = sum(1 for r in ultimas5 if r["acertou"]) / 5

    # Calcular indicadores de fadiga
    tempo_aumento_pct = ((tempo_medio_fim - tempo_medio_inicio) / tempo_medio_inicio * 100) if tempo_medio_inicio > 0 else 0
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
        motivos.append(f"Últimas 5 questões: apenas {int(acerto_ultimas5*100)}% de acerto")

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
# PROGRESS MILESTONES — Locke & Latham (2002) Goal-Setting Theory
# Celebrações em marcos de progresso = motivação sustentada
# ============================================================

@router.get("/api/study-intelligence/milestones", summary="Progress Milestones",
            description="""Verifica e retorna marcos de progresso alcançados recentemente.
Baseado em Goal-Setting Theory (Locke & Latham 2002): marcos intermediários
com feedback positivo mantêm motivação e senso de progresso.""")
def progress_milestones(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna conquistas/marcos alcançados e próximos marcos."""
    hoje = today_str()

    milestones_alcancados = []
    proximos_marcos = []

    # === Total de questões respondidas ===
    total_questoes = conn.execute(
        "SELECT COUNT(*) FROM questoes_respostas WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    marcos_questoes = [50, 100, 250, 500, 1000, 2500, 5000]
    for marco in marcos_questoes:
        if total_questoes >= marco:
            milestones_alcancados.append({
                "tipo": "questoes_total",
                "marco": marco,
                "atual": total_questoes,
                "icone": "❓",
                "titulo": f"{marco} questões respondidas!",
            })
        else:
            proximos_marcos.append({
                "tipo": "questoes_total",
                "marco": marco,
                "atual": total_questoes,
                "pct": round(total_questoes / marco * 100, 1),
                "falta": marco - total_questoes,
                "icone": "❓",
                "titulo": f"{marco} questões",
            })
            break

    # === Flashcards revisados ===
    total_flash = conn.execute(
        "SELECT COALESCE(SUM(flashcards_revisados), 0) FROM streaks WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    marcos_flash = [50, 100, 300, 500, 1000, 3000]
    for marco in marcos_flash:
        if total_flash >= marco:
            milestones_alcancados.append({
                "tipo": "flashcards_total",
                "marco": marco,
                "atual": total_flash,
                "icone": "🧠",
                "titulo": f"{marco} revisões de flashcard!",
            })
        else:
            proximos_marcos.append({
                "tipo": "flashcards_total",
                "marco": marco,
                "atual": total_flash,
                "pct": round(total_flash / marco * 100, 1),
                "falta": marco - total_flash,
                "icone": "🧠",
                "titulo": f"{marco} revisões",
            })
            break

    # === Matérias dominadas (>80% acerto + 20+ questões) ===
    materias_dominadas = conn.execute("""
        SELECT q.materia, COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        HAVING total >= 20 AND pct >= 80
    """, (user_id,)).fetchall()

    for m in materias_dominadas:
        milestones_alcancados.append({
            "tipo": "materia_dominada",
            "marco": 80,
            "atual": m["pct"],
            "icone": "🏆",
            "titulo": f"{m['materia']} dominada ({m['pct']}%)!",
            "materia": m["materia"],
        })

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
            milestones_alcancados.append({
                "tipo": "streak",
                "marco": marco,
                "atual": streak_max,
                "icone": "🔥",
                "titulo": f"Streak de {marco} dias!",
            })
        else:
            proximos_marcos.append({
                "tipo": "streak",
                "marco": marco,
                "atual": streak_atual,
                "pct": round(streak_atual / marco * 100, 1),
                "falta": marco - streak_atual,
                "icone": "🔥",
                "titulo": f"Streak de {marco} dias",
            })
            break

    # === Horas totais de estudo ===
    total_horas = conn.execute(
        "SELECT COALESCE(SUM(horas), 0) FROM sessoes_estudo WHERE user_id = ?", (user_id,)
    ).fetchone()[0]

    marcos_horas = [10, 25, 50, 100, 250, 500, 1000]
    for marco in marcos_horas:
        if total_horas >= marco:
            milestones_alcancados.append({
                "tipo": "horas_total",
                "marco": marco,
                "atual": round(total_horas, 1),
                "icone": "⏱️",
                "titulo": f"{marco}h de estudo!",
            })
        else:
            proximos_marcos.append({
                "tipo": "horas_total",
                "marco": marco,
                "atual": round(total_horas, 1),
                "pct": round(total_horas / marco * 100, 1),
                "falta": round(marco - total_horas, 1),
                "icone": "⏱️",
                "titulo": f"{marco}h de estudo",
            })
            break

    # === Progresso do edital ===
    edital_stats = conn.execute("""
        SELECT COUNT(*) as total, SUM(CASE WHEN status = 'Concluído' THEN 1 ELSE 0 END) as concluidos
        FROM edital WHERE user_id = ? AND arquivado = 0
    """, (user_id,)).fetchone()
    if edital_stats["total"] > 0:
        pct_edital = round(edital_stats["concluidos"] / edital_stats["total"] * 100, 1)
        marcos_edital = [25, 50, 75, 100]
        for marco in marcos_edital:
            if pct_edital >= marco:
                milestones_alcancados.append({
                    "tipo": "edital_progresso",
                    "marco": marco,
                    "atual": pct_edital,
                    "icone": "📋",
                    "titulo": f"Edital {marco}% concluído!",
                })
            else:
                proximos_marcos.append({
                    "tipo": "edital_progresso",
                    "marco": marco,
                    "atual": pct_edital,
                    "pct": round(pct_edital / marco * 100, 1),
                    "falta": round(marco - pct_edital, 1),
                    "icone": "📋",
                    "titulo": f"Edital {marco}%",
                })
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

@router.get("/api/study-intelligence/error-patterns", summary="Error Analysis Patterns",
            description="""Analisa padrões nos erros do usuário e categoriza as causas.
Categorias: interpretação de texto, conceito errado, exceção à regra, pegadinha/distrator, desatenção.
Permite atacar a CAUSA dos erros, não apenas revisar o conteúdo.""")
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

    erros = conn.execute(f"""
        SELECT qr.id as resposta_id, qr.tempo_segundos, qr.confianca,
               q.materia, q.dificuldade, q.enunciado, q.resposta_correta,
               qr.resposta_usuario
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ? AND qr.data >= ? AND qr.acertou = 0
        {filtro_mat}
        ORDER BY qr.id DESC
    """, params).fetchall()

    if not erros:
        return {
            "total_erros": 0,
            "padroes": [],
            "distribuicao": {},
            "recomendacoes": ["Sem erros no período analisado. Aumente a dificuldade!"],
        }

    # Classificar erros por padrão provável (heurísticas)
    padroes = {
        "desatencao": [],      # Tempo muito rápido + confiança alta
        "conceito": [],         # Tempo normal + matéria com baixo acerto geral
        "interpretacao": [],    # Tempo alto (leu mas não entendeu)
        "pegadinha": [],        # Tempo normal + confiança alta + errou
        "exceção": [],          # Alternativa próxima da correta
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
    distribuicao = {
        k: {"count": len(v), "pct": round(len(v) / total * 100, 1)}
        for k, v in padroes.items() if v
    }

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
        recomendacoes.append("🎯 Leia TODAS as alternativas antes de responder. Seu erro principal é responder rápido demais.")
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
            "desatencao": {"descricao": "Respondeu rápido demais (não leu direito)", "count": len(padroes["desatencao"])},
            "conceito": {"descricao": "Não domina o conceito/regra", "count": len(padroes["conceito"])},
            "interpretacao": {"descricao": "Dificuldade em interpretar o enunciado", "count": len(padroes["interpretacao"])},
            "pegadinha": {"descricao": "Caiu em distrator/pegadinha (confiante mas errou)", "count": len(padroes["pegadinha"])},
            "exceção": {"descricao": "Não conhecia a exceção à regra", "count": len(padroes["exceção"])},
        },
        "tecnica": "Error Analysis (metacognição + distractor analysis): entender POR QUE erra é mais eficaz que apenas revisar o conteúdo. Atacar a causa elimina categorias inteiras de erro.",
    }


# ============================================================
# RETRIEVAL PRACTICE FORÇADO — Roediger & Butler (2011)
# Recall ANTES de estudar = Testing Effect (+50% retenção vs reler)
# ============================================================

@router.get("/api/study-intelligence/retrieval-warmup", summary="Retrieval Practice Warmup",
            description="""Gera 3-5 perguntas de recall rápido ANTES de estudar um tópico.
O Testing Effect (Roediger 2011) mostra que tentar lembrar ANTES de estudar:
- Ativa conhecimento prévio (schema activation)
- Identifica lacunas (direciona atenção durante estudo)
- Melhora retenção em 50% vs simplesmente reler
Deve ser chamado ao iniciar qualquer sessão de estudo.""")
def retrieval_warmup(
    materia: str,
    topico: str = "",
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera perguntas de recall para warmup antes de estudar."""

    # 1. Buscar questões que o user JÁ RESPONDEU dessa matéria (recall de memória existente)
    params = [user_id, materia, user_id]
    filtro_topico = ""
    if topico:
        filtro_topico = "AND q.topico LIKE ?"
        params.insert(2, f"%{topico}%")

    # Priorizar questões que errou recentemente (successive relearning)
    erradas = conn.execute(f"""
        SELECT q.id, q.enunciado, q.resposta_correta, q.materia, q.topico, q.explicacao
        FROM questoes q
        JOIN questoes_respostas qr ON qr.questao_id = q.id AND qr.user_id = q.user_id
        WHERE q.user_id = ? AND q.materia = ? {filtro_topico}
        AND qr.acertou = 0
        AND q.id IN (SELECT questao_id FROM questoes_respostas WHERE user_id = ?)
        ORDER BY qr.id DESC
        LIMIT 2
    """, params).fetchall()
    recall_questions = [dict(r) for r in erradas]

    # 2. Buscar flashcards da matéria como perguntas de recall
    fc_params = [user_id, materia]
    flashcards = conn.execute("""
        SELECT id, pergunta, resposta, materia
        FROM flashcards
        WHERE user_id = ? AND materia = ?
        ORDER BY CASE
            WHEN stability > 0 AND stability < 5 THEN 0
            WHEN repetitions = 0 THEN 2
            ELSE 1
        END, RANDOM()
        LIMIT 3
    """, fc_params).fetchall()

    recall_flashcards = [{
        "id": f["id"],
        "pergunta": f["pergunta"],
        "resposta": f["resposta"],
        "tipo": "flashcard_recall",
    } for f in flashcards]

    # 3. Gerar perguntas abertas baseadas nos tópicos do edital
    topicos_edital = conn.execute("""
        SELECT topico FROM edital
        WHERE user_id = ? AND materia = ? AND arquivado = 0 AND status = 'Concluído'
        ORDER BY RANDOM() LIMIT 3
    """, (user_id, materia)).fetchall()

    perguntas_abertas = [{
        "pergunta": f"O que você lembra sobre '{t['topico']}'? Liste os pontos principais.",
        "topico": t["topico"],
        "tipo": "recall_aberto",
    } for t in topicos_edital]

    # Combinar: máx 5 itens (2 questões erradas + 2 flashcards + 1 aberta)
    warmup_items = []
    warmup_items.extend([{
        "tipo": "questao_recall",
        "id": q["id"],
        "pergunta": q["enunciado"][:200] + "..." if len(q["enunciado"]) > 200 else q["enunciado"],
        "resposta": q["resposta_correta"],
        "explicacao": q.get("explicacao", ""),
    } for q in recall_questions[:2]])

    warmup_items.extend(recall_flashcards[:2])
    warmup_items.extend(perguntas_abertas[:1])

    # Se não tem nada (matéria nova), sugerir pre-test
    if not warmup_items:
        return {
            "materia": materia,
            "modo": "pre_test",
            "items": [],
            "mensagem": f"Primeira sessão de {materia}! Comece respondendo algumas questões para mapear seu nível.",
            "sugestao": "Use o Pre-Test ou responda 5-10 questões antes de começar a teoria.",
            "tecnica": "Pre-testing Effect (Richland 2009): responder perguntas ANTES de estudar o conteúdo ativa curiosidade e direciona atenção.",
        }

    return {
        "materia": materia,
        "topico": topico or "geral",
        "modo": "retrieval_warmup",
        "items": warmup_items[:5],
        "total_items": len(warmup_items),
        "instrucao": "⚡ ANTES de estudar, tente responder cada item DE MEMÓRIA. Não consulte. Errar aqui é BOM — direciona seu estudo.",
        "mensagem": f"Warmup de {materia}: tente lembrar antes de estudar!",
        "tecnica": "Testing Effect (Roediger 2011): recall ativo antes do estudo melhora retenção em ~50% vs reler passivamente. Errar no warmup aumenta atenção durante o estudo subsequente.",
    }


@router.post("/api/study-intelligence/retrieval-warmup/resultado", summary="Registrar resultado do warmup")
def retrieval_warmup_resultado(
    materia: str = Body(...),
    acertos: int = Body(0),
    total: int = Body(0),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra o resultado do warmup para tracking de progresso."""
    from datetime import datetime
    conn.execute("""
        INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at)
        VALUES (?, 0.05, ?, 'retrieval_warmup', ?, ?)
    """, (materia, today_str(), user_id, datetime.now().isoformat()))
    conn.commit()
    pct = round(acertos / total * 100) if total > 0 else 0
    if pct >= 80:
        msg = "🧠 Excelente recall! Sua memória está forte nessa matéria."
    elif pct >= 50:
        msg = "👍 Recall parcial. O estudo de hoje vai reforçar os pontos fracos que você identificou."
    else:
        msg = "🎯 Muitas lacunas identificadas! Ótimo — agora seu cérebro está preparado para absorver o conteúdo."
    return {"ok": True, "pct_recall": pct, "mensagem": msg}


# ============================================================
# MINIMUM EFFECTIVE DOSE — Ericsson (1993) Deliberate Practice
# Tempo ótimo por matéria: não mais que o necessário, não menos
# ============================================================

@router.get("/api/study-intelligence/minimum-dose", summary="Minimum Effective Dose",
            description="""Calcula o tempo MÍNIMO necessário por matéria para progredir.
Baseado em Deliberate Practice (Ericsson 1993): qualidade > quantidade.
Matérias com >80% acerto precisam de manutenção (20min/dia).
Matérias com <50% precisam de investimento pesado (1-2h/dia).
Evita overlearning em matérias fortes e subinvestimento em fracas.""")
def minimum_effective_dose(
    horas_disponiveis: float = Query(default=3.0, description="Horas disponíveis por dia"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Calcula distribuição ótima do tempo de estudo."""

    # Buscar matérias do ciclo ativo
    ciclo = conn.execute("""
        SELECT materia FROM ciclo_estudos WHERE user_id = ? AND ativo = 1 ORDER BY ordem
    """, (user_id,)).fetchall()

    if not ciclo:
        return {"materias": [], "mensagem": "Nenhuma matéria no ciclo. Importe do edital."}

    materias_analise = []
    total_minutos = int(horas_disponiveis * 60)

    for c in ciclo:
        mat = c["materia"]

        # Taxa de acerto
        stats = conn.execute("""
            SELECT COUNT(*) as total, COALESCE(SUM(acertou), 0) as acertos
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND q.materia = ?
        """, (user_id, mat)).fetchone()
        total_q = stats["total"]
        pct_acerto = round(stats["acertos"] / total_q * 100, 1) if total_q > 0 else 0

        # Tópicos pendentes
        topicos = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN status != 'Concluído' THEN 1 ELSE 0 END) as pendentes
            FROM edital WHERE materia = ? AND user_id = ? AND arquivado = 0
        """, (mat, user_id)).fetchone()
        pct_concluido = round((topicos["total"] - (topicos["pendentes"] or 0)) / max(topicos["total"], 1) * 100, 1)

        # Flashcards pendentes
        fc_pendentes = conn.execute("""
            SELECT COUNT(*) FROM flashcards
            WHERE materia = ? AND user_id = ? AND proxima_revisao <= ?
        """, (mat, user_id, today_str())).fetchone()[0]

        # Questões em erros_revisao
        erros_pendentes = 0
        try:
            erros_pendentes = conn.execute("""
                SELECT COUNT(*) FROM erros_revisao er
                JOIN questoes q ON q.id = er.questao_id
                WHERE er.user_id = ? AND q.materia = ? AND er.proxima_revisao <= ?
            """, (user_id, mat, today_str())).fetchone()[0]
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

        materias_analise.append({
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
        })

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


# ============================================================
# IMPLEMENTATION INTENTIONS — Gollwitzer (1999)
# Compromisso pré-sessão aumenta execução em 2-3x
# ============================================================

@router.post("/api/study-intelligence/intention", summary="Registrar Implementation Intention",
             description="""Registra um micro-compromisso antes da sessão de estudo.
Baseado em Gollwitzer (1999): 'Eu vou [ação] em [hora] no [local]'
aumenta a probabilidade de execução em 2-3x comparado com apenas 'quero estudar'.""")
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
    cur = conn.execute("""
        INSERT INTO study_intentions (user_id, materia, duracao_min, atividade, meta_especifica, criado_em)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, materia, duracao_min, atividade, meta_especifica or "", now))
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
    intention = conn.execute(
        "SELECT * FROM study_intentions WHERE id = ? AND user_id = ?", (id, user_id)
    ).fetchone()
    if not intention:
        raise HTTPException(status_code=404, detail="Intenção não encontrada")

    conn.execute("""
        UPDATE study_intentions SET
            concluido = 1, reflexao = ?, real_duracao_min = ?,
            real_acertos = ?, real_questoes = ?
        WHERE id = ? AND user_id = ?
    """, (reflexao, real_duracao_min, real_acertos, real_questoes, id, user_id))
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
        historico = conn.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN concluido = 1 AND real_duracao_min >= duracao_min * 0.8 THEN 1 ELSE 0 END) as cumpridos
            FROM study_intentions
            WHERE user_id = ? AND criado_em >= date('now', '-7 days')
        """, (user_id,)).fetchall()
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
        "sugestao_proxima": f"Tente {max(15, planejado_min - 10)}min amanhã" if status == "nao_cumpriu" else f"Mantenha {planejado_min}min ou aumente para {planejado_min + 10}min",
        "tecnica": "Reflexão metacognitiva: confrontar intenção vs realidade calibra expectativas futuras e reduz o 'planning fallacy'.",
    }


@router.get("/api/study-intelligence/intention/hoje", summary="Intenções de hoje")
def intencoes_hoje(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna intenções registradas hoje (para exibir no dashboard)."""
    hoje = today_str()
    try:
        rows = conn.execute("""
            SELECT * FROM study_intentions
            WHERE user_id = ? AND criado_em >= ? AND criado_em < date(?, '+1 day')
            ORDER BY criado_em
        """, (user_id, hoje, hoje)).fetchall()
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
        "mensagem": f"📋 {concluidas}/{total} sessões concluídas hoje" if total > 0 else "Nenhum compromisso registrado hoje. Declare uma intenção para começar!",
    }


# ============================================================
# BANCA-SPECIFIC TRAINING — Perfil de Banca para Concursos
# Cada banca tem padrões previsíveis: treinar o estilo = +15-20%
# ============================================================

# Perfis das bancas (dados compilados de análises especializadas)
_BANCA_PROFILES = {
    "CESPE": {
        "nome_completo": "CEBRASPE (antigo CESPE/UnB)",
        "formato_principal": "certo_errado",
        "penalizacao": True,
        "penalizacao_valor": -1.0,
        "estilo": "Raciocínio e aplicação prática. Interdisciplinar. Doutrina + Jurisprudência.",
        "caracteristicas": [
            "Formato Certo/Errado: 1 erro anula 1 acerto → NÃO CHUTE se < 70% certeza",
            "Enunciados longos e contextualizados (casos hipotéticos)",
            "Cobra doutrina + jurisprudência (STF/STJ) além da letra da lei",
            "Questões interdisciplinares (mix de matérias num item)",
            "Poucas questões de 'decoreba' — prioriza raciocínio",
            "Pegadinhas com palavras absolutas: SEMPRE, NUNCA, SOMENTE, TODOS",
            "Exceções são cobradas frequentemente",
        ],
        "dicas_estrategicas": [
            "Só responda se tiver > 70% de certeza (penalização é severa)",
            "Cuidado com palavras absolutas (sempre, nunca, exclusivamente) → geralmente errado",
            "Leia CADA PALAVRA do enunciado — detalhes mudam o sentido",
            "Estude jurisprudência: informativos STF e STJ são fonte frequente",
            "Se metade do item está certo e metade errado → marque ERRADO",
            "Treine com provas CESPE anteriores do MESMO ÓRGÃO se possível",
        ],
        "disciplinas_destaque": {
            "Português": "Foco em interpretação de texto, inferências, gramática aplicada",
            "Direito": "Doutrina + jurisprudência + exceções. Lei seca NÃO basta",
            "Informática": "Conceitos práticos, segurança, comandos Linux",
            "Administração": "Teorias + aplicação em casos hipotéticos",
        },
        "armadilhas_comuns": [
            "Item parcialmente correto (parte certa + detalhe errado = ERRADO)",
            "Troca de sujeito/complemento (quem faz o quê)",
            "Exceção apresentada como regra geral",
            "Jurisprudência desatualizada (cobrar decisão antiga já superada)",
            "Generalização indevida (ex: 'todos os servidores' quando há exceção)",
        ],
        "threshold_responder": 0.70,  # Só responder se > 70% certeza
    },
    "CEBRASPE": None,  # Alias → usar CESPE
    "FCC": {
        "nome_completo": "Fundação Carlos Chagas",
        "formato_principal": "multipla_escolha",
        "penalizacao": False,
        "penalizacao_valor": 0,
        "estilo": "Provas extensas, enunciados detalhados. Forte em interpretação e lei seca com aplicação.",
        "caracteristicas": [
            "Múltipla escolha com 5 alternativas (A-E), sem penalização",
            "Provas EXTENSAS: gestão de tempo é crucial",
            "Português: textos longos + interpretação profunda",
            "Direito: mix de literalidade da lei + aplicação prática (casos hipotéticos)",
            "Evoluiu de 'letra da lei pura' para interpretação contextualizada",
            "Alternativas bem construídas — eliminação por absurdo funciona pouco",
            "Bastante cobrança de reescrita de frases (Português)",
        ],
        "dicas_estrategicas": [
            "RESPONDA TUDO — não há penalização por erro",
            "Gerencie TEMPO: provas são longas, marque questões difíceis e volte depois",
            "Português é DECISIVO: treine interpretação e reescrita de frases",
            "Estude jurisprudência consolidada (STF/STJ) para Direito",
            "Treine com provas FCC de TRIBUNAIS (padrão mais consistente)",
            "Leia TODO o enunciado antes de olhar as alternativas",
        ],
        "disciplinas_destaque": {
            "Português": "Interpretação de texto + sintaxe + reescrita + pontuação",
            "Direito": "Literalidade da lei + jurisprudência consolidada + casos práticos",
            "Raciocínio Lógico": "Lógica formal + tabelas-verdade + problemas matemáticos",
            "Informática": "Office + segurança da informação + conceitos de internet",
        },
        "armadilhas_comuns": [
            "Alternativa 'quase certa' que muda um detalhe (sinônimo inexato)",
            "Enunciado longo que induz a pular — a resposta está no detalhe",
            "Ordem das alternativas: correta raramente é A ou E (tendência B/C/D)",
            "Reescrita que muda sutilmente o sentido (coesão/coerência)",
            "Caso prático onde a exceção se aplica mas parece regra geral",
        ],
        "threshold_responder": 0.0,  # Responda TUDO (sem penalização)
    },
    "FGV": {
        "nome_completo": "Fundação Getúlio Vargas",
        "formato_principal": "multipla_escolha",
        "penalizacao": False,
        "penalizacao_valor": 0,
        "estilo": "Alto nível técnico. Sem padrão fixo — varia por órgão. Exigente e imprevisível.",
        "caracteristicas": [
            "Múltipla escolha com 5 alternativas, sem penalização",
            "NÃO tem padrão fixo — varia conforme o órgão contratante",
            "Português: ~50% é interpretação de texto (vai além da gramática)",
            "Raciocínio Lógico: gosta de matemática pura (geometria, combinatória, porcentagem)",
            "Direito: cobra teoria + aplicação, nível alto",
            "Imprevisível: pode mudar o estilo entre provas diferentes",
            "Nível médio-alto a alto (OAB é FGV)",
        ],
        "dicas_estrategicas": [
            "RESPONDA TUDO — não há penalização",
            "Estude provas anteriores do MESMO ÓRGÃO (FGV muda estilo por cliente)",
            "Português: domine interpretação de texto (50%+ da prova de PT)",
            "Raciocínio Lógico: foque em matemática pura, não apenas lógica proposicional",
            "Direito: estude tanto doutrina quanto jurisprudência",
            "A FGV é criativa: espere questões 'diferentes' do usual",
        ],
        "disciplinas_destaque": {
            "Português": "Interpretação de texto (50%+) + gramática aplicada ao texto",
            "Raciocínio Lógico": "Matemática pura: geometria, combinatória, porcentagem, regra de 3",
            "Direito": "Teoria + jurisprudência + questões interpretativas",
            "Atualidades": "Temas da atualidade podem aparecer em qualquer disciplina",
        },
        "armadilhas_comuns": [
            "Questão com 2 alternativas muito parecidas (diferença sutil)",
            "Interpretação de texto com resposta 'parcialmente certa'",
            "Questão de RLM que parece simples mas tem pegadinha numérica",
            "Direito: alternativa com jurisprudência minoritária como se fosse majoritária",
            "Enunciado que muda contexto no meio (leia até o final)",
        ],
        "threshold_responder": 0.0,  # Responda TUDO
    },
    "VUNESP": {
        "nome_completo": "Fundação Vunesp",
        "formato_principal": "multipla_escolha",
        "penalizacao": False,
        "penalizacao_valor": 0,
        "estilo": "Concursos estaduais SP. Cobrança direta, menos interpretativa que FCC/FGV.",
        "caracteristicas": [
            "Múltipla escolha (5 alternativas), sem penalização",
            "Forte em concursos do estado de São Paulo",
            "Português: gramática normativa + interpretação (mais direta que FCC)",
            "Questões mais objetivas e menos rebuscadas",
            "Cobrança de legislação específica do órgão",
        ],
        "dicas_estrategicas": [
            "RESPONDA TUDO — sem penalização",
            "Português mais 'gramatical' que interpretativo",
            "Estude a legislação ESPECÍFICA do órgão",
            "Questões tendem a ser mais diretas — tempo menos pressionado",
        ],
        "disciplinas_destaque": {
            "Português": "Gramática normativa + interpretação direta",
            "Legislação": "Lei específica do órgão (estatuto, regimento)",
        },
        "armadilhas_comuns": [
            "Questão aparentemente fácil com detalhe de legislação específica",
            "Gramática: concordância com sujeito distante do verbo",
        ],
        "threshold_responder": 0.0,
    },
}

# Alias
_BANCA_PROFILES["CEBRASPE"] = _BANCA_PROFILES["CESPE"]


@router.get("/api/study-intelligence/banca-profile", summary="Perfil da Banca",
            description="""Retorna perfil detalhado da banca organizadora do concurso com:
- Características de prova, estilo de cobrança
- Dicas estratégicas específicas
- Armadilhas comuns
- Threshold de confiança para responder (C/E vs múltipla escolha)
- Disciplinas com foco diferenciado

Bancas disponíveis: CESPE/CEBRASPE, FCC, FGV, VUNESP""")
def banca_profile(
    banca: str = Query("", description="Nome da banca (CESPE, FCC, FGV, VUNESP)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna perfil da banca com dicas estratégicas."""
    # Se não informou banca, tentar detectar do edital
    if not banca:
        try:
            edital_info = conn.execute("""
                SELECT banca FROM edital_info WHERE user_id = ? AND banca != '' LIMIT 1
            """, (user_id,)).fetchone()
            if edital_info:
                banca = edital_info["banca"]
        except Exception:
            pass

    if not banca:
        return {
            "banca": None,
            "mensagem": "Informe a banca ou cadastre no edital. Bancas disponíveis: CESPE, FCC, FGV, VUNESP",
            "bancas_disponiveis": list(k for k in _BANCA_PROFILES.keys() if _BANCA_PROFILES[k] is not None),
        }

    banca_upper = banca.upper().strip()
    profile = _BANCA_PROFILES.get(banca_upper)
    if not profile:
        # Tentar match parcial
        for key, val in _BANCA_PROFILES.items():
            if val and banca_upper in key:
                profile = val
                banca_upper = key
                break

    if not profile:
        return {
            "banca": banca,
            "mensagem": f"Banca '{banca}' não encontrada. Disponíveis: CESPE, FCC, FGV, VUNESP",
            "bancas_disponiveis": list(k for k in _BANCA_PROFILES.keys() if _BANCA_PROFILES[k] is not None),
        }

    # Estatísticas do user com essa banca (se tiver questões classificadas por banca)
    stats_banca = None
    try:
        row = conn.execute("""
            SELECT COUNT(*) as total,
                   COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND UPPER(q.banca) LIKE ?
        """, (user_id, f"%{banca_upper}%")).fetchone()
        if row and row["total"] > 0:
            stats_banca = {
                "total_questoes": row["total"],
                "acertos": row["acertos"],
                "pct_acerto": round(row["acertos"] / row["total"] * 100, 1),
            }
    except Exception:
        pass

    return {
        "banca": banca_upper,
        "profile": profile,
        "stats_usuario": stats_banca,
        "recomendacao_chute": "NÃO CHUTE — penalização severa" if profile["penalizacao"] else "RESPONDA TUDO — sem penalização",
    }


@router.get("/api/study-intelligence/banca-training", summary="Banca-Specific Training Session",
            description="Gera sessão de treino específica para o estilo da banca do concurso.")
def banca_training_session(
    banca: str = Query(..., description="Banca (CESPE, FCC, FGV, VUNESP)"),
    quantidade: int = Query(10, description="Quantidade de questões"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera sessão focada no estilo da banca."""
    banca_upper = banca.upper().strip()
    if banca_upper == "CEBRASPE":
        banca_upper = "CESPE"
    profile = _BANCA_PROFILES.get(banca_upper)
    if not profile:
        raise HTTPException(status_code=400, detail=f"Banca '{banca}' não encontrada")

    # Buscar questões DESSA BANCA no banco
    questoes_banca = conn.execute("""
        SELECT q.id, q.enunciado, q.materia, q.dificuldade, q.alternativa_c
        FROM questoes q
        WHERE q.user_id = ? AND UPPER(q.banca) LIKE ?
        ORDER BY RANDOM() LIMIT ?
    """, (user_id, f"%{banca_upper}%", quantidade * 2)).fetchall()

    # Se não tem questões classificadas por banca, usar formato
    if not questoes_banca or len(questoes_banca) < quantidade:
        # Usar formato como proxy: CESPE = C/E (sem alternativa_c), FCC/FGV = múltipla
        if profile["formato_principal"] == "certo_errado":
            questoes_formato = conn.execute("""
                SELECT id, enunciado, materia, dificuldade
                FROM questoes WHERE user_id = ?
                AND (alternativa_c IS NULL OR alternativa_c = '')
                ORDER BY RANDOM() LIMIT ?
            """, (user_id, quantidade)).fetchall()
        else:
            questoes_formato = conn.execute("""
                SELECT id, enunciado, materia, dificuldade
                FROM questoes WHERE user_id = ?
                AND alternativa_c IS NOT NULL AND alternativa_c != ''
                ORDER BY RANDOM() LIMIT ?
            """, (user_id, quantidade)).fetchall()
        questoes_banca = questoes_formato

    ids = [q["id"] for q in questoes_banca[:quantidade]]

    # Dica pré-sessão baseada na banca
    dica_pre = profile["dicas_estrategicas"][0] if profile["dicas_estrategicas"] else ""

    return {
        "banca": banca_upper,
        "questao_ids": ids,
        "total": len(ids),
        "formato": profile["formato_principal"],
        "penalizacao": profile["penalizacao"],
        "dica_pre_sessao": dica_pre,
        "armadilhas_para_vigiar": profile["armadilhas_comuns"][:3],
        "threshold_confianca": profile["threshold_responder"],
        "instrucao": f"Treine como se fosse prova {profile['nome_completo']}. {'NÃO CHUTE se < 70% certeza!' if profile['penalizacao'] else 'Responda TODAS — sem penalização.'}",
    }


# ============================================================
# EXAM ANXIETY EXPOSURE — Exposição Gradual a Pressão de Prova
# Baseado em literatura de test anxiety (Zeidner 1998, Hembree 1988)
# Dessensibilização sistemática: pressão gradual reduz ansiedade
# ============================================================

@router.get("/api/study-intelligence/anxiety-exposure", summary="Exam Anxiety Exposure Config",
            description="""Gera configuração de simulado com pressão gradual para dessensibilização.
4 níveis progressivos de estresse simulado:
- Nível 1 (Confortável): tempo normal, sem pressão
- Nível 2 (Moderado): tempo -20%, cronômetro visível
- Nível 3 (Realista): tempo -20% + nota de corte visível + penalização C/E
- Nível 4 (Alta pressão): tempo -30% + nota corte + penalização + ranking

Baseado em Zeidner (1998): exposição gradual a condições de prova reduz ansiedade
em 40-60% após 4-6 sessões. Hembree (1988): meta-análise confirma eficácia.""")
def anxiety_exposure_config(
    nivel: int = Query(1, description="Nível de pressão (1-4)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna configuração de simulado com nível de ansiedade progressivo."""

    # Detectar nível recomendado baseado no histórico
    nivel_recomendado = 1
    try:
        simulados_feitos = conn.execute("""
            SELECT COUNT(*) FROM simulados WHERE user_id = ? AND status = 'finalizado'
        """, (user_id,)).fetchone()[0]

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
            "tempo_fator": 1.0,        # Tempo normal
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
            "tempo_fator": 0.80,        # 20% menos tempo
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
            "penalizacao": True,         # -1 por erro (estilo CESPE)
            "nota_corte_visivel": True,   # Nota de corte aparece durante o simulado
            "cronometro_visivel": True,
            "ranking_visivel": False,
            "distracoes": False,
            "mensagem_pressao": "⚠️ Penalização ativa: 1 erro anula 1 acerto. Nota de corte: 60%.",
            "descricao": "Condições de prova CESPE: penalização + nota de corte visível.",
        },
        4: {
            "nome": "Alta Pressão",
            "emoji": "🥵",
            "tempo_fator": 0.70,         # 30% menos tempo
            "penalizacao": True,
            "nota_corte_visivel": True,
            "cronometro_visivel": True,
            "ranking_visivel": True,      # Mostra posição vs outros candidatos (bots)
            "distracoes": True,           # Alertas aleatórios simulando ambiente de prova
            "mensagem_pressao": "🔥 ALTA PRESSÃO: tempo -30%, penalização, nota de corte, ranking ao vivo. Respire fundo.",
            "descricao": "Simulação máxima de estresse. Se passar aqui, passa na prova real.",
        },
    }

    config = configs[nivel]

    # Calcular tempo com fator
    tempo_base_min = 180  # 3h padrão
    try:
        # Buscar do edital_info se existir
        ei = conn.execute(
            "SELECT tempo_prova_min FROM edital_info WHERE user_id = ? LIMIT 1", (user_id,)
        ).fetchone()
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
        dicas_anti_ansiedade.append("💪 Lembre: isso é TREINO. A prova real será mais fácil porque você já treinou sob pressão.")

    return {
        "nivel": nivel,
        "nivel_recomendado": nivel_recomendado,
        "config": config,
        "tempo_base_min": tempo_base_min,
        "tempo_ajustado_min": tempo_ajustado,
        "nota_corte": nota_corte,
        "dicas_anti_ansiedade": dicas_anti_ansiedade,
        "progresso_exposicao": {
            "simulados_feitos": simulados_feitos if 'simulados_feitos' in dir() else 0,
            "proximo_nivel_em": max(0, (nivel * 4) - (simulados_feitos if 'simulados_feitos' in dir() else 0)),
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

    conn.execute("""
        INSERT INTO anxiety_exposure_log (user_id, nivel, nota, tempo_seg, completou, ansiedade_antes, ansiedade_depois, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, nivel, nota, tempo_seg, int(completou), ansiedade_antes, ansiedade_depois, datetime.now().isoformat()))
    conn.commit()

    # Calcular progresso (redução de ansiedade ao longo do tempo)
    historico = conn.execute("""
        SELECT ansiedade_antes, ansiedade_depois, nivel, nota
        FROM anxiety_exposure_log WHERE user_id = ?
        ORDER BY id DESC LIMIT 10
    """, (user_id,)).fetchall()

    reducao_media = 0
    if historico:
        reducoes = [r["ansiedade_antes"] - r["ansiedade_depois"] for r in historico if r["ansiedade_antes"] and r["ansiedade_depois"]]
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
        "recomendacao": f"Continue no nível {nivel}" if diff >= 0 else f"Tente nível {max(1, nivel-1)} na próxima",
    }


# ============================================================
# PEER TEACHING — Webb (1991), Fiorella & Mayer (2013)
# Ensinar = processamento profundo + detecção de lacunas
# "Se não consegue explicar, não entendeu de verdade"
# ============================================================

@router.get("/api/study-intelligence/peer-teaching", summary="Peer Teaching Suggestion",
            description="""Sugere tópicos para o user ENSINAR a outros (no chat, grupo ou Study Room).
Ensinar produz 'generative learning' — força reorganização do conhecimento.
Baseado em Webb (1991): quem explica retém 90% vs 10% de quem apenas lê.
Fiorella & Mayer (2013): 'learning by teaching' é uma das técnicas mais eficazes.""")
def peer_teaching_suggestion(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Sugere tópicos ideais para ensinar (domínio suficiente mas não perfeito)."""
    hoje = today_str()

    # Tópicos ideais para ensinar: acerto entre 70-90% (sabe o suficiente mas ensinar consolida)
    materias_para_ensinar = conn.execute("""
        SELECT q.materia,
               COUNT(*) as total,
               ROUND(CAST(SUM(qr.acertou) AS FLOAT) / COUNT(*) * 100, 1) as pct_acerto
        FROM questoes_respostas qr
        JOIN questoes q ON q.id = qr.questao_id
        WHERE qr.user_id = ?
        GROUP BY q.materia
        HAVING total >= 10 AND pct_acerto BETWEEN 70 AND 92
        ORDER BY pct_acerto DESC
    """, (user_id,)).fetchall()

    sugestoes = []
    for m in materias_para_ensinar[:5]:
        # Buscar tópico específico dessa matéria que tem bom domínio
        topico = conn.execute("""
            SELECT topico FROM edital
            WHERE materia = ? AND user_id = ? AND status = 'Concluído' AND arquivado = 0
            ORDER BY RANDOM() LIMIT 1
        """, (m["materia"], user_id)).fetchone()

        sugestoes.append({
            "materia": m["materia"],
            "pct_acerto": m["pct_acerto"],
            "total_questoes": m["total"],
            "topico_sugerido": topico["topico"] if topico else None,
            "como_ensinar": _gerar_prompt_ensino(m["materia"], topico["topico"] if topico else ""),
        })

    # Verificar se já ensinou recentemente (XP bonus tracking)
    xp_ensino = 0
    try:
        ensinos = conn.execute("""
            SELECT COUNT(*) as total FROM peer_teaching_log
            WHERE user_id = ? AND created_at >= date('now', '-7 days')
        """, (user_id,)).fetchone()
        xp_ensino = (ensinos["total"] or 0) * 30  # 30 XP por ensino
    except Exception:
        pass

    return {
        "sugestoes": sugestoes,
        "total_sugestoes": len(sugestoes),
        "xp_ensino_semana": xp_ensino,
        "mensagem": "🎓 Ensinar é a forma mais eficaz de aprender! Escolha um tópico e explique para alguém (chat, grupo ou Study Room).",
        "beneficios": [
            "Retenção de 90% (vs 10% de leitura passiva)",
            "Identifica lacunas: se não consegue explicar, precisa revisar",
            "Reforça conexões neurais pelo processamento generativo",
            "Ganha 30 XP por cada sessão de ensino registrada",
        ],
        "tecnica": "Peer Teaching (Webb 1991, Fiorella & Mayer 2013): explicar para outros força reorganização do conhecimento e detecção de lacunas. Pirâmide de aprendizagem: ensinar = 90% retenção.",
    }


def _gerar_prompt_ensino(materia: str, topico: str) -> str:
    """Gera prompt/desafio para ensinar o tópico."""
    if topico:
        return f"Explique '{topico}' como se estivesse ensinando para um colega que nunca estudou {materia}. Use exemplos práticos."
    return f"Escolha um conceito de {materia} que você domina e explique em no máximo 3 parágrafos, como se fosse para alguém que está começando."


@router.post("/api/study-intelligence/peer-teaching/registrar", summary="Registrar sessão de ensino")
def peer_teaching_registrar(
    materia: str = Body(...),
    topico: str = Body(""),
    formato: str = Body("texto", description="texto, audio, video, chat, studyroom"),
    duracao_min: int = Body(5),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Registra que o user ensinou algo (dá XP bônus)."""
    from datetime import datetime

    conn.execute("""
        CREATE TABLE IF NOT EXISTS peer_teaching_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            materia TEXT NOT NULL,
            topico TEXT DEFAULT '',
            formato TEXT DEFAULT 'texto',
            duracao_min INTEGER DEFAULT 5,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_peer_teaching_user ON peer_teaching_log(user_id)")

    conn.execute("""
        INSERT INTO peer_teaching_log (user_id, materia, topico, formato, duracao_min, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, materia, topico, formato, duracao_min, datetime.now().isoformat()))

    # Registrar como sessão de estudo (tipo 'ensino')
    horas = duracao_min / 60
    conn.execute("""
        INSERT INTO sessoes_estudo (materia, horas, data, tipo, user_id, created_at)
        VALUES (?, ?, ?, 'ensino', ?, ?)
    """, (materia, round(horas, 3), today_str(), user_id, datetime.now().isoformat()))

    conn.commit()

    return {
        "ok": True,
        "xp_ganho": 30,
        "mensagem": f"🎓 +30 XP por ensinar {materia}! Ensinar é a forma mais eficaz de fixar conhecimento.",
    }

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

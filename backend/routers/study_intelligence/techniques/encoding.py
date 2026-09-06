"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from datetime import date, timedelta

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from utils import today_str

router = APIRouter(prefix="", tags=["Study Intelligence"])


# ============================================================
# GET /api/study-intelligence/contextual-variation — Mesmo tópico, formatos diferentes
# ============================================================


@router.get(
    "/api/study-intelligence/contextual-variation",
    summary="Variação contextual",
    description="""Retorna o mesmo tópico em formatos diferentes para melhorar transferência.
Estudar o mesmo conceito como flashcard, questão, dissertativa e explicação oral
melhora a capacidade de aplicar o conhecimento em contextos novos.""",
)
def contextual_variation(
    materia: str, topico: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)
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
        variations.append(
            {
                "formato": "flashcard",
                "icone": "🧠",
                "instrucao": "Tente responder mentalmente antes de revelar",
                "conteudo": {"pergunta": f["pergunta"], "resposta": f["resposta"]},
                "id": f["id"],
            }
        )

    # 2. Questão format (existe?)
    q_query = "SELECT id, enunciado, alternativa_a, alternativa_b, alternativa_c, alternativa_d, resposta_correta FROM questoes WHERE user_id = ? AND materia = ?"
    q_params = [user_id, materia]
    if topico:
        q_query += " AND topico = ?"
        q_params.append(topico)
    q_query += " ORDER BY RANDOM() LIMIT 2"
    questoes = conn.execute(q_query, q_params).fetchall()
    for q in questoes:
        variations.append(
            {
                "formato": "questao",
                "icone": "❓",
                "instrucao": "Responda a questão objetiva",
                "conteudo": {
                    "enunciado": q["enunciado"],
                    "alternativas": {
                        "A": q["alternativa_a"],
                        "B": q["alternativa_b"],
                        "C": q["alternativa_c"],
                        "D": q["alternativa_d"],
                    },
                    "resposta": q["resposta_correta"],
                },
                "id": q["id"],
            }
        )

    # 3. Dissertativa format (gerado)
    variations.append(
        {
            "formato": "dissertativa",
            "icone": "✍️",
            "instrucao": "Escreva um parágrafo explicando este conceito com suas palavras",
            "conteudo": {
                "prompt": f"Explique com suas palavras o conceito de '{topico or materia}'. Use exemplos práticos.",
                "tempo_sugerido": "3-5 minutos",
            },
            "id": None,
        }
    )

    # 4. Ensinar format (Feynman Technique)
    variations.append(
        {
            "formato": "ensinar",
            "icone": "🎓",
            "instrucao": "Imagine que está ensinando isso a alguém que nunca estudou o tema. Explique em voz alta.",
            "conteudo": {
                "prompt": f"Ensine '{topico or materia}' como se estivesse explicando para um leigo. Se travar, identifique a lacuna.",
                "dica": "Se não conseguir explicar de forma simples, é sinal de que precisa revisar o fundamento.",
            },
            "id": None,
        }
    )

    # 5. Mapa mental (connections)
    variations.append(
        {
            "formato": "conexoes",
            "icone": "🔗",
            "instrucao": "Liste 3 conexões entre este tópico e outros que você já estudou",
            "conteudo": {
                "prompt": f"Como '{topico or materia}' se conecta com outros temas? Liste pelo menos 3 relações.",
                "exemplo": "Ex: 'Direito Penal > Princípio da Legalidade' se conecta com 'Direito Constitucional > Art. 5º' e com 'Direito Administrativo > Legalidade'",
            },
            "id": None,
        }
    )

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


@router.get(
    "/api/study-intelligence/successive-relearning",
    summary="Successive Relearning",
    description="""Identifica tópicos que precisam de ciclos de re-aprendizagem.
Successive Relearning = retrieval practice + spaced repetition em ciclos:
Estudar → Testar → Espaçar → Re-testar → Espaçar mais → Re-testar...
Até atingir critério de domínio (3 acertos consecutivos).""",
)
def successive_relearning(conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Retorna tópicos que estão presos em baixo domínio e precisam de ciclos de re-learning."""
    hoje = date.today()
    trinta_dias = (hoje - timedelta(days=30)).isoformat()

    # Identificar tópicos com "stuck mastery": muitas tentativas mas acurácia não sobe
    stuck_topics = conn.execute(
        """
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
    """,
        (user_id, user_id, user_id, trinta_dias),
    ).fetchall()

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

        cycles.append(
            {
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
            }
        )

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


@router.get(
    "/api/study-intelligence/dual-coding",
    summary="Dual Coding suggestions",
    description="""Sugere representações visuais para tópicos estudados.
Dual Coding: combinar informação verbal (texto) + visual (diagrama/imagem) cria 2 caminhos
independentes de memória, dobrando as chances de recall.""",
)
def dual_coding(materia: str, topico: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
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
            "SELECT pergunta, resposta FROM flashcards WHERE user_id = ? AND materia = ? LIMIT 5", (user_id, materia)
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
            {"tipo": v["tipo"], "icone": v["icone"], "instrucao": v["instrucao"]} for v in visual_templates.values()
        ],
        "conteudo_para_visualizar": content_items,
        "dica_geral": "Não precisa ser bonito! Um rabisco simples no papel ou um diagrama rápido já ativa o canal visual da memória. O importante é CRIAR, não copiar.",
    }


# ============================================================
# GET /api/study-intelligence/concrete-examples — Exemplos concretos
# ============================================================


@router.get(
    "/api/study-intelligence/concrete-examples",
    summary="Concrete examples",
    description="""Gera exemplos concretos e analogias do mundo real para conceitos abstratos.
Exemplos concretos ancoram conceitos abstratos na memória de longo prazo.""",
)
def concrete_examples(
    materia: str, topico: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)
):
    """Retorna exemplos concretos para um tópico (gerados por templates ou IA)."""

    # Base de exemplos por matéria (templates comuns para concursos)
    exemplos_base = {
        "Direito Constitucional": [
            {
                "conceito": "Princípio da Legalidade",
                "exemplo": "Um servidor público só pode fazer o que a lei autoriza. Se não há lei permitindo, está proibido. É como um cardápio: só pode pedir o que está escrito.",
            },
            {
                "conceito": "Habeas Corpus",
                "exemplo": "João foi preso sem mandado e sem flagrante. Ele pode pedir HC para ser solto imediatamente — é como um 'botão de emergência' contra prisão ilegal.",
            },
            {
                "conceito": "Cláusula Pétrea",
                "exemplo": "Imagine a Constituição como uma casa. As cláusulas pétreas são as vigas de sustentação — você pode reformar paredes (emendar), mas nunca mexer nas vigas.",
            },
        ],
        "Direito Penal": [
            {
                "conceito": "Dolo Eventual",
                "exemplo": "Motorista bêbado: 'sei que posso matar alguém, mas tanto faz, vou dirigir assim mesmo'. Ele não QUER matar, mas ACEITA o risco.",
            },
            {
                "conceito": "Culpa Consciente",
                "exemplo": "Malabarista com facas: 'sei que posso machucar alguém, mas confio na minha habilidade'. Ele prevê o risco mas acredita sinceramente que não vai acontecer.",
            },
            {
                "conceito": "Legítima Defesa",
                "exemplo": "Ladrão armado invade sua casa. Você o empurra e ele cai. Usou força proporcional contra agressão injusta e atual — legítima defesa perfeita.",
            },
        ],
        "Direito Administrativo": [
            {
                "conceito": "Impessoalidade",
                "exemplo": "Prefeito inaugura obra com placa 'Obra do Prefeito Silva'. ERRADO — a obra é do município, não da pessoa. É como um funcionário de banco: age em nome do banco, não dele.",
            },
            {
                "conceito": "Discricionariedade",
                "exemplo": "Lei diz: 'prefeitura PODE construir praça'. O prefeito decide onde e quando. Mas se a lei diz 'DEVE construir', não tem escolha.",
            },
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


@router.get(
    "/api/study-intelligence/memory-palace",
    summary="Memory Palace / Method of Loci",
    description="""Guia para criar um Palácio da Memória para listas e sequências.
O Method of Loci (Palácio da Memória) usa memória espacial para ancorar informações.
Ideal para: artigos de lei, princípios, listas de requisitos, prazos.""",
)
def memory_palace(materia: str, topico: str = "", conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Guia para construir um Palácio da Memória para o tópico."""

    # Buscar items que são "listas" (princípios, requisitos, etc.)
    items_to_memorize = []
    try:
        # Flashcards dessa matéria que parecem ser listas
        cards = conn.execute(
            """
            SELECT pergunta, resposta FROM flashcards
            WHERE user_id = ? AND materia = ?
            AND (resposta LIKE '%,%,%' OR resposta LIKE '%1)%' OR resposta LIKE '%•%'
                 OR pergunta LIKE '%quais%' OR pergunta LIKE '%requisitos%'
                 OR pergunta LIKE '%princípios%' OR pergunta LIKE '%elementos%')
            LIMIT 5
        """,
            (user_id, materia),
        ).fetchall()
        items_to_memorize = [{"pergunta": c["pergunta"], "resposta": c["resposta"]} for c in cards]
    except Exception:
        pass

    # Palácio template
    palace_template = {
        "nome": "Sua Casa",
        "locais": [
            {
                "posicao": 1,
                "local": "🚪 Porta de entrada",
                "dica": "Primeiro item da lista — visualize algo enorme bloqueando a porta",
            },
            {
                "posicao": 2,
                "local": "🛋️ Sala / Sofá",
                "dica": "Segundo item — imagine sentado no sofá fazendo algo absurdo",
            },
            {"posicao": 3, "local": "📺 TV / Estante", "dica": "Terceiro item — a TV está mostrando algo relacionado"},
            {
                "posicao": 4,
                "local": "🍳 Cozinha / Geladeira",
                "dica": "Quarto item — está dentro da geladeira, congelado",
            },
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
            {
                "local": "Porta",
                "item": "Legalidade",
                "imagem": "Um juiz GIGANTE bloqueia a porta com um livro de leis. Você SÓ passa se mostrar a lei autorizando.",
            },
            {
                "local": "Sala",
                "item": "Impessoalidade",
                "imagem": "Todas as pessoas no sofá estão sem rosto — são idênticas, impessoais.",
            },
            {
                "local": "Cozinha",
                "item": "Moralidade",
                "imagem": "Sua avó está na cozinha olhando feio — ela julga se suas ações são morais.",
            },
            {
                "local": "Banheiro",
                "item": "Publicidade",
                "imagem": "O espelho do banheiro é na verdade uma TV transmitindo tudo ao vivo para o público.",
            },
            {
                "local": "Quarto",
                "item": "Eficiência",
                "imagem": "Um robô super-eficiente está arrumando seu quarto em 2 segundos.",
            },
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
# POST /api/study-intelligence/elaboration — Salvar elaboração (A3)
# ============================================================


@router.post(
    "/api/study-intelligence/elaboration",
    summary="Salvar elaboration log",
    description="Registra a resposta do aluno a um prompt elaborativo.",
)
def save_elaboration(body: dict, conn=Depends(get_db_session), user_id: int = Depends(get_user_id)):
    """Grava na tabela elaboration_log.
    body: {flashcard_id ou questao_id, prompt_tipo, resposta_usuario}
    """
    flashcard_id = body.get("flashcard_id")
    questao_id = body.get("questao_id")
    prompt_tipo = body.get("prompt_tipo", "")
    resposta_usuario = body.get("resposta_usuario", "")

    if not prompt_tipo:
        raise HTTPException(status_code=400, detail="prompt_tipo é obrigatório")

    conn.execute(
        """
        INSERT INTO elaboration_log (user_id, flashcard_id, questao_id, prompt_tipo, resposta_usuario, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """,
        (user_id, flashcard_id, questao_id, prompt_tipo, resposta_usuario, today_str()),
    )
    conn.commit()

    return {"ok": True, "message": "Elaboração registrada com sucesso"}

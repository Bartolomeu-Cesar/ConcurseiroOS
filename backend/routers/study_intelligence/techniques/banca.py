"""Técnicas modernas de estudo: pre-testing, self-explanation, calibration, etc."""

from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db_session

router = APIRouter(prefix="", tags=["Study Intelligence"])


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


@router.get(
    "/api/study-intelligence/banca-profile",
    summary="Perfil da Banca",
    description="""Retorna perfil detalhado da banca organizadora do concurso com:
- Características de prova, estilo de cobrança
- Dicas estratégicas específicas
- Armadilhas comuns
- Threshold de confiança para responder (C/E vs múltipla escolha)
- Disciplinas com foco diferenciado

Bancas disponíveis: CESPE/CEBRASPE, FCC, FGV, VUNESP""",
)
def banca_profile(
    banca: str = Query("", description="Nome da banca (CESPE, FCC, FGV, VUNESP)"),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna perfil da banca com dicas estratégicas."""
    # Se não informou banca, tentar detectar do edital
    if not banca:
        try:
            edital_info = conn.execute(
                """
                SELECT banca FROM edital_info WHERE user_id = ? AND banca != '' LIMIT 1
            """,
                (user_id,),
            ).fetchone()
            if edital_info:
                banca = edital_info["banca"]
        except Exception:
            pass

    if not banca:
        return {
            "banca": None,
            "mensagem": "Informe a banca ou cadastre no edital. Bancas disponíveis: CESPE, FCC, FGV, VUNESP",
            "bancas_disponiveis": list(k for k in _BANCA_PROFILES if _BANCA_PROFILES[k] is not None),
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
            "bancas_disponiveis": list(k for k in _BANCA_PROFILES if _BANCA_PROFILES[k] is not None),
        }

    # Estatísticas do user com essa banca (se tiver questões classificadas por banca)
    stats_banca = None
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) as total,
                   COALESCE(SUM(qr.acertou), 0) as acertos
            FROM questoes_respostas qr
            JOIN questoes q ON q.id = qr.questao_id
            WHERE qr.user_id = ? AND UPPER(q.banca) LIKE ?
        """,
            (user_id, f"%{banca_upper}%"),
        ).fetchone()
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
        "recomendacao_chute": "NÃO CHUTE — penalização severa"
        if profile["penalizacao"]
        else "RESPONDA TUDO — sem penalização",
    }


@router.get(
    "/api/study-intelligence/banca-training",
    summary="Banca-Specific Training Session",
    description="Gera sessão de treino específica para o estilo da banca do concurso.",
)
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
    questoes_banca = conn.execute(
        """
        SELECT q.id, q.enunciado, q.materia, q.dificuldade, q.alternativa_c
        FROM questoes q
        WHERE q.user_id = ? AND UPPER(q.banca) LIKE ?
        ORDER BY RANDOM() LIMIT ?
    """,
        (user_id, f"%{banca_upper}%", quantidade * 2),
    ).fetchall()

    # Se não tem questões classificadas por banca, usar formato
    if not questoes_banca or len(questoes_banca) < quantidade:
        # Usar formato como proxy: CESPE = C/E (sem alternativa_c), FCC/FGV = múltipla
        if profile["formato_principal"] == "certo_errado":
            questoes_formato = conn.execute(
                """
                SELECT id, enunciado, materia, dificuldade
                FROM questoes WHERE user_id = ?
                AND (alternativa_c IS NULL OR alternativa_c = '')
                ORDER BY RANDOM() LIMIT ?
            """,
                (user_id, quantidade),
            ).fetchall()
        else:
            questoes_formato = conn.execute(
                """
                SELECT id, enunciado, materia, dificuldade
                FROM questoes WHERE user_id = ?
                AND alternativa_c IS NOT NULL AND alternativa_c != ''
                ORDER BY RANDOM() LIMIT ?
            """,
                (user_id, quantidade),
            ).fetchall()
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

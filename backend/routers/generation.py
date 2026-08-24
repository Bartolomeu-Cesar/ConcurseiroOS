"""Generation Mode — Active Recall sem alternativas (C2).

O Generation Effect mostra que GERAR a resposta de memória é 40% mais efetivo
que reconhecimento (múltipla escolha). Este módulo implementa um modo de estudo
onde o aluno responde SEM ver alternativas.
"""
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Query

from database import get_db_session
from deps import get_user_id
from logger import log
from schemas import ResponderGeracaoRequest
from utils import today_str, update_streak

router = APIRouter(prefix="", tags=["Generation Mode"])


# ============================================================
# HELPERS
# ============================================================

def _normalize_text(text: str) -> str:
    """Remove acentos, lowercase, strip pontuação."""
    if not text:
        return ""
    # Remove acentos
    nfkd = unicodedata.normalize("NFKD", text)
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Lowercase e remove pontuação
    cleaned = re.sub(r"[^\w\s]", "", without_accents.lower())
    return cleaned.strip()


def _match_resposta(digitada: str, correta_letra: str, alternativas: dict) -> dict:
    """Algoritmo de fuzzy match para comparar resposta digitada com a correta.

    Args:
        digitada: Texto digitado pelo usuário
        correta_letra: Letra da resposta correta (A, B, C, D, E)
        alternativas: Dict com {a: texto, b: texto, ...}

    Returns:
        dict com {score, acertou, feedback}
    """
    digitada_clean = digitada.strip()
    digitada_norm = _normalize_text(digitada_clean)
    correta_letra_upper = correta_letra.upper().strip()
    correta_letra_lower = correta_letra_upper.lower()

    # 1) Exact letter match: "C", "c", "letra c", "alternativa c"
    letter_patterns = [
        correta_letra_lower,
        f"letra {correta_letra_lower}",
        f"alternativa {correta_letra_lower}",
        correta_letra_upper,
    ]
    if digitada_norm in [_normalize_text(p) for p in letter_patterns]:
        return {"score": 1.0, "acertou": True, "feedback": "Resposta exata (letra)!"}

    # Se digitou apenas uma letra e é a correta
    if len(digitada_clean) == 1 and digitada_clean.upper() == correta_letra_upper:
        return {"score": 1.0, "acertou": True, "feedback": "Resposta exata (letra)!"}

    # 2) Text match: comparar com texto da alternativa correta
    texto_correto = alternativas.get(correta_letra_lower, "")
    texto_correto_norm = _normalize_text(texto_correto)

    if not texto_correto_norm:
        # Fallback: se não tem texto da alternativa, só aceita letra
        return {"score": 0.0, "acertou": False, "feedback": "Não foi possível avaliar. Resposta correta: " + correta_letra_upper}

    # 2a) Match exato do texto
    if digitada_norm == texto_correto_norm:
        return {"score": 1.0, "acertou": True, "feedback": "Resposta exata (texto completo)!"}

    # 2b) Substring match: resposta contém palavras-chave da alternativa
    palavras_corretas = set(texto_correto_norm.split())
    palavras_digitadas = set(digitada_norm.split())

    # Remover palavras comuns/stop words
    stop_words = {"a", "o", "e", "de", "da", "do", "das", "dos", "em", "no", "na",
                  "um", "uma", "que", "se", "os", "as", "por", "para", "com", "nao",
                  "ao", "ou", "ser", "ter", "esta", "sao", "foi", "pelo", "pela",
                  "seu", "sua", "mais", "como", "mas", "quando", "entre", "sobre"}

    palavras_corretas_sig = palavras_corretas - stop_words
    palavras_digitadas_sig = palavras_digitadas - stop_words

    # Percentual de palavras significativas da resposta correta que aparecem na digitada
    if palavras_corretas_sig:
        keyword_overlap = len(palavras_digitadas_sig & palavras_corretas_sig) / len(palavras_corretas_sig)
    else:
        keyword_overlap = 0.0

    # 2c) Similarity ratio (SequenceMatcher)
    similarity = SequenceMatcher(None, digitada_norm, texto_correto_norm).ratio()

    # Score final: média ponderada
    score = max(keyword_overlap * 0.6 + similarity * 0.4, similarity)

    # Também verificar se a resposta digitada é substring substancial
    if len(digitada_norm) >= 10 and digitada_norm in texto_correto_norm:
        score = max(score, 0.8)

    # Classificação
    if score >= 0.7:
        return {"score": round(score, 2), "acertou": True, "feedback": "Correto! Boa memória."}
    elif score >= 0.4:
        return {"score": round(score, 2), "acertou": False, "feedback": "Parcialmente correto. Quase lá!"}
    else:
        return {"score": round(score, 2), "acertou": False, "feedback": "Incorreto. Revise este conteúdo."}


def _gerar_lacunas(enunciado: str) -> dict:
    """Gera versão 'completar lacuna' de um enunciado.

    Identifica:
    - Palavras com >= 5 letras que começam com maiúscula (nomes próprios/conceitos)
    - Termos entre aspas

    Substitui por '___' (max 3 lacunas).

    Returns:
        dict com {enunciado_lacuna, lacunas: [palavras], dica: str}
    """
    lacunas = []
    enunciado_mod = enunciado

    # 1) Termos entre aspas
    aspas_pattern = r'"([^"]+)"'
    termos_aspas = re.findall(aspas_pattern, enunciado)
    for termo in termos_aspas[:2]:  # Max 2 de aspas
        if len(lacunas) >= 3:
            break
        lacunas.append(termo)
        enunciado_mod = enunciado_mod.replace(f'"{termo}"', '"___"', 1)

    # 2) Palavras com >= 5 letras que começam com maiúscula (não no início de frase)
    # Padrão: não está após ". " ou no início do texto
    if len(lacunas) < 3:
        # Split em sentenças e pegar palavras capitalizadas que não são início de frase
        palavras = re.findall(r'(?<=[a-záéíóúâêîôûãõç]\s)([A-ZÁÉÍÓÚÂÊÎÔÛÃÕ][a-záéíóúâêîôûãõç]{4,})', enunciado_mod)
        for palavra in palavras:
            if len(lacunas) >= 3:
                break
            if palavra not in lacunas:
                lacunas.append(palavra)
                enunciado_mod = enunciado_mod.replace(palavra, "___", 1)

    # 3) Se ainda não tem lacunas, buscar termos jurídicos/técnicos comuns (palavras longas)
    if len(lacunas) < 2:
        palavras_longas = re.findall(r'\b([A-ZÁÉÍÓÚÂÊÎÔÛÃÕ]{2,}[a-záéíóúâêîôûãõç]*(?:\s[A-ZÁÉÍÓÚÂÊÎÔÛÃÕ][a-záéíóúâêîôûãõç]+)*)\b', enunciado_mod)
        for p in palavras_longas:
            if len(p) >= 5 and p not in lacunas and p != "___" and len(lacunas) < 3:
                lacunas.append(p)
                enunciado_mod = enunciado_mod.replace(p, "___", 1)

    # Gerar dica (primeira letra de cada lacuna)
    dica = ", ".join(f"{l[0]}..." for l in lacunas) if lacunas else ""

    return {
        "enunciado_lacuna": enunciado_mod,
        "lacunas": lacunas,
        "num_lacunas": len(lacunas),
        "dica": dica,
    }


# ============================================================
# ENDPOINTS
# ============================================================

@router.get("/api/questoes/modo-geracao", summary="Buscar questões para modo geração",
            description="Retorna questões SEM alternativas para active recall. Prioriza erradas > nunca respondidas > aleatório.")
def get_questoes_geracao(
    materia: str = "",
    limit: int = Query(10, ge=1, le=50),
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Retorna questões sem alternativas para o modo geração."""
    params_base = [user_id]
    where_materia = ""
    if materia:
        where_materia = " AND q.materia = ?"
        params_base.append(materia)

    questoes = []

    # 1) Prioridade: questões já erradas no modo geração
    query_erradas = f"""
        SELECT DISTINCT q.id, q.enunciado, q.materia, q.topico, q.dificuldade
        FROM questoes q
        INNER JOIN generation_responses gr ON gr.questao_id = q.id AND gr.user_id = ?
        WHERE q.user_id = ? AND gr.acertou = 0{where_materia}
        ORDER BY RANDOM()
        LIMIT ?
    """
    params_erradas = [user_id] + params_base + [limit]
    rows = conn.execute(query_erradas, params_erradas).fetchall()
    for r in rows:
        questoes.append(dict(r))

    remaining = limit - len(questoes)
    if remaining <= 0:
        return questoes[:limit]

    # 2) Questões nunca respondidas em modo geração
    ids_ja = [q["id"] for q in questoes]
    placeholders = ",".join("?" * len(ids_ja)) if ids_ja else "0"

    query_novas = f"""
        SELECT q.id, q.enunciado, q.materia, q.topico, q.dificuldade
        FROM questoes q
        WHERE q.user_id = ?
          AND q.id NOT IN (SELECT questao_id FROM generation_responses WHERE user_id = ?)
          AND q.id NOT IN ({placeholders})
          {where_materia.replace('q.materia', 'q.materia')}
        ORDER BY RANDOM()
        LIMIT ?
    """
    params_novas = [user_id, user_id] + ids_ja + ([materia] if materia else []) + [remaining]
    rows = conn.execute(query_novas, params_novas).fetchall()
    for r in rows:
        questoes.append(dict(r))

    remaining = limit - len(questoes)
    if remaining <= 0:
        return questoes[:limit]

    # 3) Aleatório (qualquer questão restante)
    ids_ja = [q["id"] for q in questoes]
    placeholders = ",".join("?" * len(ids_ja)) if ids_ja else "0"

    query_random = f"""
        SELECT q.id, q.enunciado, q.materia, q.topico, q.dificuldade
        FROM questoes q
        WHERE q.user_id = ?
          AND q.id NOT IN ({placeholders})
          {where_materia.replace('q.materia', 'q.materia')}
        ORDER BY RANDOM()
        LIMIT ?
    """
    params_random = [user_id] + ids_ja + ([materia] if materia else []) + [remaining]
    rows = conn.execute(query_random, params_random).fetchall()
    for r in rows:
        questoes.append(dict(r))

    return questoes[:limit]


@router.post("/api/questoes/{questao_id}/responder-geracao", summary="Responder questão no modo geração",
             description="Envia resposta digitada e recebe feedback com match score.")
def responder_geracao(
    questao_id: int,
    body: ResponderGeracaoRequest,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Processa resposta do modo geração com fuzzy matching."""
    # Buscar questão
    questao = conn.execute(
        "SELECT * FROM questoes WHERE id = ? AND user_id = ?",
        (questao_id, user_id)
    ).fetchone()

    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    questao_dict = dict(questao)
    resposta_correta_letra = questao_dict["resposta_correta"].strip().upper()

    # Montar dict de alternativas
    alternativas = {
        "a": questao_dict.get("alternativa_a", ""),
        "b": questao_dict.get("alternativa_b", ""),
        "c": questao_dict.get("alternativa_c", ""),
        "d": questao_dict.get("alternativa_d", ""),
        "e": questao_dict.get("alternativa_e", ""),
    }

    # Executar match
    resultado = _match_resposta(body.resposta_digitada, resposta_correta_letra, alternativas)
    acertou = 1 if resultado["acertou"] else 0

    # Texto da alternativa correta
    alternativa_correta_texto = alternativas.get(resposta_correta_letra.lower(), "")

    # Gravar em generation_responses
    conn.execute("""
        INSERT INTO generation_responses (user_id, questao_id, resposta_digitada, resposta_correta, match_score, acertou, tempo_ms, modo, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'geracao', ?)
    """, (user_id, questao_id, body.resposta_digitada, resposta_correta_letra, resultado["score"], acertou, body.tempo_ms, today_str()))

    # Também gravar em questoes_respostas para histórico unificado
    conn.execute("""
        INSERT INTO questoes_respostas (questao_id, resposta_usuario, acertou, tempo_segundos, data, user_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (questao_id, body.resposta_digitada, acertou, body.tempo_ms // 1000, today_str(), user_id))

    # Atualizar streak
    update_streak(conn, "questoes_resolvidas", user_id=user_id)

    conn.commit()

    # Buscar explicação se existir
    explicacao = questao_dict.get("explicacao", "")

    return {
        "acertou": bool(acertou),
        "match_score": resultado["score"],
        "resposta_correta": resposta_correta_letra,
        "alternativa_correta_texto": alternativa_correta_texto,
        "feedback": resultado["feedback"],
        "explicacao": explicacao if explicacao else None,
    }


@router.get("/api/questoes/modo-geracao/stats", summary="Estatísticas do modo geração",
            description="Métricas de desempenho no modo geração com comparativo vs múltipla escolha.")
def stats_geracao(
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Estatísticas do usuário no modo geração."""
    # Total respondidas no modo geração
    row = conn.execute(
        "SELECT COUNT(*) as total, SUM(acertou) as acertos, AVG(match_score) as media_score FROM generation_responses WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    total = row["total"] or 0
    acertos = row["acertos"] or 0
    media_score = round(row["media_score"] or 0.0, 2)
    pct_acerto = round((acertos / total * 100) if total > 0 else 0.0, 1)

    # Por matéria
    rows_materia = conn.execute("""
        SELECT q.materia, COUNT(*) as total, SUM(gr.acertou) as acertos
        FROM generation_responses gr
        INNER JOIN questoes q ON q.id = gr.questao_id
        WHERE gr.user_id = ?
        GROUP BY q.materia
        ORDER BY total DESC
    """, (user_id,)).fetchall()

    por_materia = []
    for r in rows_materia:
        mat_total = r["total"]
        mat_acertos = r["acertos"] or 0
        por_materia.append({
            "materia": r["materia"],
            "total": mat_total,
            "acertos": mat_acertos,
            "pct": round((mat_acertos / mat_total * 100) if mat_total > 0 else 0.0, 1),
        })

    # Comparativo com múltipla escolha
    row_mc = conn.execute(
        "SELECT COUNT(*) as total, SUM(acertou) as acertos FROM questoes_respostas WHERE user_id = ?",
        (user_id,)
    ).fetchone()

    total_mc = row_mc["total"] or 0
    acertos_mc = row_mc["acertos"] or 0
    pct_mc = round((acertos_mc / total_mc * 100) if total_mc > 0 else 0.0, 1)

    return {
        "total_respondidas": total,
        "pct_acerto": pct_acerto,
        "media_score": media_score,
        "por_materia": por_materia,
        "comparativo_mc": {
            "pct_acerto_geracao": pct_acerto,
            "pct_acerto_multipla_escolha": pct_mc,
            "diferenca": round(pct_acerto - pct_mc, 1),
        },
    }


@router.get("/api/questoes/{questao_id}/completar-lacuna", summary="Gerar versão completar lacuna",
            description="Transforma o enunciado em exercício de completar lacunas, identificando conceitos-chave.")
def completar_lacuna(
    questao_id: int,
    conn=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera versão 'completar lacuna' de uma questão."""
    questao = conn.execute(
        "SELECT id, enunciado, materia, topico, dificuldade FROM questoes WHERE id = ? AND user_id = ?",
        (questao_id, user_id)
    ).fetchone()

    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    questao_dict = dict(questao)
    resultado = _gerar_lacunas(questao_dict["enunciado"])

    return {
        "id": questao_dict["id"],
        "enunciado_lacuna": resultado["enunciado_lacuna"],
        "num_lacunas": resultado["num_lacunas"],
        "dica": resultado["dica"],
        "lacunas": resultado["lacunas"],
    }

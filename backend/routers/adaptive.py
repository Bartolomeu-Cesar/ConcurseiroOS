"""Router de Sessão Adaptativa / Computerized Adaptive Testing (C1).

Implementa sessão de estudo que adapta a dificuldade das questões em tempo real,
mantendo o aluno na zona de flow (65-80% de acerto).

Modelo IRT simplificado (1-PL):
- theta: habilidade estimada do aluno (inicia em 0)
- dificuldade: Fácil=-1, Médio=0, Difícil=1
- P(acerto) = 1 / (1 + exp(-(theta - difficulty_value)))
- Atualização: theta += 0.4*(1-P) se acertou, theta -= 0.4*P se errou
"""
import math
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from database import get_db_session
from deps import get_user_id
from schemas import IniciarAdaptativaRequest, ResponderAdaptativaRequest

router = APIRouter(tags=["Sessão Adaptativa"])

# Mapeamento de dificuldade para valor numérico IRT
DIFFICULTY_MAP = {"Fácil": -1.0, "Médio": 0.0, "Difícil": 1.0}
# Ordem de fallback: se não achar questão da dificuldade alvo
DIFFICULTY_ORDER = ["Fácil", "Médio", "Difícil"]


def _theta_to_difficulty(theta: float) -> str:
    """Mapeia theta para dificuldade-alvo."""
    if theta < -0.5:
        return "Fácil"
    elif theta > 0.5:
        return "Difícil"
    return "Médio"


def _calc_zona_flow(respostas_recentes: list[int]) -> str:
    """Calcula zona de flow baseada nas últimas 5 respostas."""
    if not respostas_recentes:
        return "aquecimento"
    pct = sum(respostas_recentes) / len(respostas_recentes) * 100
    if pct < 50:
        return "abaixo"
    elif pct < 65:
        return "aquecimento"
    elif pct <= 80:
        return "flow"
    return "conforto"


def _normalizar_dificuldade(dificuldade: str | None) -> str:
    """Normaliza o campo dificuldade. Vazio ou None → 'Médio'."""
    if not dificuldade or dificuldade.strip() == "":
        return "Médio"
    return dificuldade.strip()


# ============================================================
# POST /api/sessao-adaptativa/iniciar
# ============================================================

@router.post("/api/sessao-adaptativa/iniciar", summary="Iniciar sessão adaptativa",
             description="Cria uma sessão de estudo adaptativa que ajusta a dificuldade em tempo real.")
def iniciar_sessao_adaptativa(body: IniciarAdaptativaRequest,
                              conn=Depends(get_db_session),
                              user_id: int = Depends(get_user_id)):
    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    materia = body.materia or ""

    conn.execute(
        """INSERT INTO sessao_adaptativa
           (user_id, session_id, materia, theta, questoes_respondidas, acertos,
            dificuldade_atual, status, started_at)
           VALUES (?, ?, ?, 0.0, 0, 0, 'Médio', 'ativa', ?)""",
        (user_id, session_id, materia, now),
    )
    conn.commit()

    return {
        "ok": True,
        "session_id": session_id,
        "materia": materia,
        "total_questoes": body.total_questoes,
    }


# ============================================================
# GET /api/sessao-adaptativa/{session_id}/proxima
# ============================================================

@router.get("/api/sessao-adaptativa/{session_id}/proxima",
            summary="Próxima questão adaptativa",
            description="Seleciona a próxima questão baseada no theta atual do aluno.")
def proxima_questao(session_id: str,
                    conn=Depends(get_db_session),
                    user_id: int = Depends(get_user_id)):
    # Buscar sessão
    sessao = conn.execute(
        "SELECT * FROM sessao_adaptativa WHERE session_id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()

    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    if sessao["status"] != "ativa":
        raise HTTPException(status_code=400, detail="Sessão já finalizada")

    theta = sessao["theta"]
    materia = sessao["materia"]
    dificuldade_alvo = _theta_to_difficulty(theta)

    # IDs já respondidos nesta sessão
    respondidas = conn.execute(
        "SELECT questao_id FROM sessao_adaptativa_respostas WHERE session_id = ?",
        (session_id,),
    ).fetchall()
    ids_respondidas = [r["questao_id"] for r in respondidas]

    # Buscar questão da dificuldade alvo
    questao = _buscar_questao(conn, materia, dificuldade_alvo, ids_respondidas, user_id)

    # Fallback: tentar dificuldades adjacentes
    if not questao:
        for diff in DIFFICULTY_ORDER:
            if diff != dificuldade_alvo:
                questao = _buscar_questao(conn, materia, diff, ids_respondidas, user_id)
                if questao:
                    break

    if not questao:
        # Sem mais questões disponíveis — finalizar sessão
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE sessao_adaptativa SET status = 'finalizada', finished_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()
        raise HTTPException(status_code=404, detail="Sem questões disponíveis para esta sessão")

    # Calcular zona de flow atual
    ultimas = conn.execute(
        """SELECT acertou FROM sessao_adaptativa_respostas
           WHERE session_id = ? ORDER BY id DESC LIMIT 5""",
        (session_id,),
    ).fetchall()
    zona_flow = _calc_zona_flow([r["acertou"] for r in ultimas])

    total_respondidas = sessao["questoes_respondidas"]

    return {
        "ok": True,
        "questao": {
            "id": questao["id"],
            "materia": questao["materia"],
            "topico": questao["topico"] or "",
            "enunciado": questao["enunciado"],
            "alternativa_a": questao["alternativa_a"],
            "alternativa_b": questao["alternativa_b"],
            "alternativa_c": questao["alternativa_c"],
            "alternativa_d": questao["alternativa_d"],
            "alternativa_e": questao["alternativa_e"] or "",
            "dificuldade": _normalizar_dificuldade(questao["dificuldade"]),
        },
        "dificuldade_alvo": dificuldade_alvo,
        "theta_atual": round(theta, 3),
        "zona_flow": zona_flow,
        "progresso": total_respondidas,
    }


def _buscar_questao(conn, materia: str, dificuldade: str, ids_respondidas: list, user_id: int):
    """Busca uma questão da matéria com dificuldade alvo não respondida nesta sessão."""
    placeholders = ""
    params = []

    # Base query
    query = "SELECT * FROM questoes WHERE 1=1"

    # Filtro de matéria (se especificada)
    if materia:
        query += " AND materia = ?"
        params.append(materia)

    # Filtro de dificuldade (considerar vazio como 'Médio')
    if dificuldade == "Médio":
        query += " AND (dificuldade = ? OR dificuldade = '' OR dificuldade IS NULL)"
        params.append(dificuldade)
    else:
        query += " AND dificuldade = ?"
        params.append(dificuldade)

    # Excluir já respondidas
    if ids_respondidas:
        placeholders = ",".join("?" for _ in ids_respondidas)
        query += f" AND id NOT IN ({placeholders})"
        params.extend(ids_respondidas)

    # Filtrar por user_id (questões podem ser do user ou globais user_id=1)
    query += " AND (user_id = ? OR user_id = 1)"
    params.append(user_id)

    query += " ORDER BY RANDOM() LIMIT 1"

    return conn.execute(query, params).fetchone()


# ============================================================
# POST /api/sessao-adaptativa/{session_id}/responder
# ============================================================

@router.post("/api/sessao-adaptativa/{session_id}/responder",
             summary="Responder questão adaptativa",
             description="Registra resposta, atualiza theta com modelo IRT e retorna feedback.")
def responder_questao(session_id: str,
                      body: ResponderAdaptativaRequest,
                      conn=Depends(get_db_session),
                      user_id: int = Depends(get_user_id)):
    # Buscar sessão
    sessao = conn.execute(
        "SELECT * FROM sessao_adaptativa WHERE session_id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()

    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")
    if sessao["status"] != "ativa":
        raise HTTPException(status_code=400, detail="Sessão já finalizada")

    # Buscar questão
    questao = conn.execute(
        "SELECT * FROM questoes WHERE id = ?",
        (body.questao_id,),
    ).fetchone()

    if not questao:
        raise HTTPException(status_code=404, detail="Questão não encontrada")

    # Determinar se acertou
    resposta_correta = (questao["resposta_correta"] or "").strip().upper()
    resposta_usuario = (body.resposta or "").strip().upper()
    acertou = 1 if resposta_usuario == resposta_correta else 0

    # Atualizar theta com modelo logístico (1-PL IRT)
    theta = sessao["theta"]
    dificuldade_questao = _normalizar_dificuldade(questao["dificuldade"])
    difficulty_value = DIFFICULTY_MAP.get(dificuldade_questao, 0.0)

    # P(acerto) = 1 / (1 + exp(-(theta - difficulty_value)))
    p = 1.0 / (1.0 + math.exp(-(theta - difficulty_value)))

    if acertou:
        theta_novo = theta + 0.4 * (1.0 - p)
    else:
        theta_novo = theta - 0.4 * p

    # Limitar theta em range razoável [-3, 3]
    theta_novo = max(-3.0, min(3.0, theta_novo))

    now = datetime.now().isoformat()

    # Salvar resposta
    conn.execute(
        """INSERT INTO sessao_adaptativa_respostas
           (session_id, questao_id, acertou, tempo_ms, dificuldade_questao, theta_pos, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (session_id, body.questao_id, acertou, body.tempo_ms, dificuldade_questao, theta_novo, now),
    )

    # Atualizar sessão
    novas_respondidas = sessao["questoes_respondidas"] + 1
    novos_acertos = sessao["acertos"] + acertou
    proxima_dificuldade = _theta_to_difficulty(theta_novo)

    conn.execute(
        """UPDATE sessao_adaptativa
           SET theta = ?, questoes_respondidas = ?, acertos = ?,
               dificuldade_atual = ?
           WHERE session_id = ?""",
        (theta_novo, novas_respondidas, novos_acertos, proxima_dificuldade, session_id),
    )
    conn.commit()

    # Calcular zona de flow (últimas 5)
    ultimas = conn.execute(
        """SELECT acertou FROM sessao_adaptativa_respostas
           WHERE session_id = ? ORDER BY id DESC LIMIT 5""",
        (session_id,),
    ).fetchall()
    zona_flow = _calc_zona_flow([r["acertou"] for r in ultimas])

    # Feedback contextual
    feedback = _gerar_feedback(zona_flow, acertou, dificuldade_questao)

    return {
        "ok": True,
        "acertou": bool(acertou),
        "resposta_correta": questao["resposta_correta"],
        "theta_novo": round(theta_novo, 3),
        "zona_flow": zona_flow,
        "proxima_dificuldade": proxima_dificuldade,
        "feedback": feedback,
        "progresso": novas_respondidas,
    }


def _gerar_feedback(zona: str, acertou: int, dificuldade: str) -> str:
    """Gera feedback motivacional baseado na zona e resultado."""
    if zona == "flow":
        if acertou:
            return "🔥 Você está na zona! Continue assim."
        return "💪 Erro calculado. A dificuldade vai ajustar para manter o ritmo."
    elif zona == "conforto":
        if acertou:
            return "⬆️ Muito fácil para você! Aumentando o desafio."
        return "Bom, vamos equilibrar o nível."
    elif zona == "abaixo":
        if acertou:
            return "👍 Boa! Recuperando o ritmo."
        return "⬇️ Diminuindo a dificuldade para encontrar seu ritmo."
    else:  # aquecimento
        if acertou:
            return "✅ Bom começo! Aquecendo..."
        return "Sem problema, ainda estamos calibrando."


# ============================================================
# GET /api/sessao-adaptativa/{session_id}/resultado
# ============================================================

@router.get("/api/sessao-adaptativa/{session_id}/resultado",
            summary="Resultado da sessão adaptativa",
            description="Retorna o resultado completo da sessão com evolução de theta.")
def resultado_sessao(session_id: str,
                     conn=Depends(get_db_session),
                     user_id: int = Depends(get_user_id)):
    # Buscar sessão
    sessao = conn.execute(
        "SELECT * FROM sessao_adaptativa WHERE session_id = ? AND user_id = ?",
        (session_id, user_id),
    ).fetchone()

    if not sessao:
        raise HTTPException(status_code=404, detail="Sessão não encontrada")

    # Finalizar sessão se ainda ativa
    if sessao["status"] == "ativa":
        now = datetime.now().isoformat()
        conn.execute(
            "UPDATE sessao_adaptativa SET status = 'finalizada', finished_at = ? WHERE session_id = ?",
            (now, session_id),
        )
        conn.commit()

    # Buscar todas as respostas
    respostas = conn.execute(
        """SELECT questao_id, acertou, dificuldade_questao, theta_pos, created_at
           FROM sessao_adaptativa_respostas
           WHERE session_id = ?
           ORDER BY id ASC""",
        (session_id,),
    ).fetchall()

    total = len(respostas)
    acertos = sum(1 for r in respostas if r["acertou"])
    pct = round((acertos / total * 100) if total > 0 else 0, 1)

    # Evolução
    evolucao = []
    for i, r in enumerate(respostas):
        evolucao.append({
            "questao_num": i + 1,
            "acertou": bool(r["acertou"]),
            "theta": round(r["theta_pos"], 3),
            "dificuldade": r["dificuldade_questao"],
        })

    # Zona predominante (moda das zonas por janelas de 5)
    zonas_count = {"flow": 0, "aquecimento": 0, "abaixo": 0, "conforto": 0}
    for i in range(len(respostas)):
        janela = [respostas[j]["acertou"] for j in range(max(0, i - 4), i + 1)]
        z = _calc_zona_flow(janela)
        zonas_count[z] = zonas_count.get(z, 0) + 1
    zona_predominante = max(zonas_count, key=zonas_count.get) if zonas_count else "aquecimento"

    # Sugestão para próxima sessão
    theta_final = sessao["theta"]
    if pct >= 80:
        sugestao = "Aumente a dificuldade! Você domina esse nível."
    elif pct >= 65:
        sugestao = "Nível perfeito. Continue praticando nessa faixa."
    elif pct >= 50:
        sugestao = "Bom progresso. Mantenha a prática para consolidar."
    else:
        sugestao = "Revise a teoria antes da próxima sessão adaptativa."

    return {
        "ok": True,
        "total": total,
        "acertos": acertos,
        "pct": pct,
        "theta_final": round(theta_final, 3),
        "theta_inicial": 0.0,
        "evolucao": evolucao,
        "zona_predominante": zona_predominante,
        "sugestao_proxima_sessao": sugestao,
        "materia": sessao["materia"],
    }

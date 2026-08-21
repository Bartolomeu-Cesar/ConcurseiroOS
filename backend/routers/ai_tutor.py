"""
AI Tutor Router - ConcurseiroOS
Integrates with OpenAI API (GPT-4o-mini) or local Ollama for AI-powered study assistance.
"""

import json
import os
from datetime import date, datetime
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_db_session
from deps import get_user_id
from logger import log

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DAILY_TOKEN_LIMIT_FREE = 50_000

SYSTEM_PROMPTS = {
    "explain_error": """Você é um professor especialista em concursos públicos brasileiros. 
O aluno errou uma questão. Explique o erro usando o método socrático:
1. Identifique a confusão conceitual
2. Explique o conceito correto de forma simples
3. Dê um exemplo prático
4. Indique um macete para lembrar
Seja direto, use linguagem acessível e referências à legislação quando relevante.""",

    "generate_flashcards": """Você é um especialista em criar flashcards para estudo de concursos.
Crie flashcards no formato JSON: [{"pergunta": "...", "resposta": "..."}]
Regras:
- Perguntas objetivas e específicas
- Respostas concisas (máx 2 frases)
- Foque nos pontos mais cobrados em provas
- Use linguagem técnica mas acessível""",

    "simplify_law": """Você é um professor de Direito que simplifica textos legais.
Transforme o texto jurídico em linguagem simples e direta:
1. Mantenha o sentido jurídico correto
2. Use analogias do cotidiano
3. Destaque palavras-chave
4. Indique exceções importantes""",

    "feynman_check": """Você é um avaliador da técnica Feynman.
O aluno tentou explicar um conceito com suas palavras.
Avalie:
1. A explicação está correta? (Sim/Parcialmente/Não)
2. Que pontos estão faltando ou incorretos?
3. Sugira uma versão melhorada
4. Dê nota de 0-100 para a compreensão demonstrada.""",

    "generate_questions": """Você é um elaborador de questões para concursos públicos.
Crie questões no formato de múltipla escolha (A-E).
Formato JSON: [{"enunciado": "...", "alternativa_a": "...", "alternativa_b": "...", "alternativa_c": "...", "alternativa_d": "...", "alternativa_e": "...", "resposta_correta": "A", "explicacao": "..."}]
Regras:
- Questões no estilo CESPE/CEBRASPE ou FCC
- Enunciados claros e objetivos  
- Distratores plausíveis
- Explicação da resposta correta""",

    "study_tips": """Você é um coach de estudos especialista em concursos públicos.
Dê dicas práticas e actionáveis baseadas no contexto do aluno.
Seja motivador mas realista. Foque em eficiência e resultados.""",
}

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class ExplainErrorRequest(BaseModel):
    questao_id: Optional[int] = None
    enunciado: Optional[str] = None
    resposta_usuario: Optional[str] = None
    resposta_correta: Optional[str] = None
    explicacao: Optional[str] = None


class GenerateFlashcardsRequest(BaseModel):
    topico: str
    quantidade: int = Field(default=5, ge=1, le=20)
    materia: str = ""
    salvar: bool = False


class SimplifyRequest(BaseModel):
    texto: str


class FeynmanCheckRequest(BaseModel):
    topico: str
    explicacao: str


class GenerateQuestionsRequest(BaseModel):
    topico: str
    quantidade: int = Field(default=3, ge=1, le=10)
    estilo: str = "cespe"
    materia: str = ""
    salvar: bool = False


class AIChatRequest(BaseModel):
    mensagem: str
    contexto: str = ""


# ---------------------------------------------------------------------------
# LLM Integration (synchronous httpx)
# ---------------------------------------------------------------------------


def _get_ai_config() -> dict:
    """Return current AI configuration."""
    return {
        "api_key": os.environ.get("OPENAI_API_KEY", ""),
        "ollama_url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        "model": os.environ.get("AI_MODEL", "gpt-4o-mini"),
    }


def call_llm_sync(messages: list[dict], max_tokens: int = 1000) -> tuple[str, int]:
    """Call LLM synchronously and return (response_text, tokens_used)."""
    config = _get_ai_config()
    api_key = config["api_key"]
    ollama_url = config["ollama_url"]
    model = config["model"]

    if api_key:
        # OpenAI-compatible API
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.7,
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data["choices"][0]["message"]["content"]
                tokens = data.get("usage", {}).get("total_tokens", 0)
                return text, tokens
        except httpx.HTTPStatusError as e:
            log.error(f"OpenAI API error: {e.response.status_code} - {e.response.text}")
            raise HTTPException(
                status_code=502,
                detail=f"Erro na API OpenAI: {e.response.status_code}",
            )
        except httpx.RequestError as e:
            log.error(f"OpenAI request error: {e}")
            raise HTTPException(
                status_code=503,
                detail="Não foi possível conectar à API OpenAI.",
            )
    else:
        # Try Ollama
        try:
            with httpx.Client(timeout=60) as client:
                response = client.post(
                    f"{ollama_url}/api/chat",
                    json={
                        "model": model,
                        "messages": messages,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                text = data.get("message", {}).get("content", "")
                tokens = data.get("eval_count", len(text) // 4)
                return text, tokens
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            log.error(f"Ollama error: {e}")
            raise HTTPException(
                status_code=503,
                detail="AI não disponível. Configure OPENAI_API_KEY ou inicie o Ollama localmente.",
            )


# ---------------------------------------------------------------------------
# Token Budget Helpers
# ---------------------------------------------------------------------------


def _get_today_str() -> str:
    return date.today().isoformat()


def _get_user_plan(db, user_id: int) -> str:
    """Get user plan. Returns 'free' or 'ilimitado'."""
    try:
        row = db.execute(
            "SELECT plan FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row:
            return row[0] if row[0] else "free"
    except Exception:
        pass
    return "free"


def _get_daily_usage(db, user_id: int) -> dict:
    """Get today's token usage for user."""
    today = _get_today_str()
    row = db.execute(
        "SELECT tokens_used, requests_count FROM ai_usage WHERE user_id = ? AND data = ?",
        (user_id, today),
    ).fetchone()
    if row:
        return {"tokens_used": row[0], "requests_count": row[1]}
    return {"tokens_used": 0, "requests_count": 0}


def _check_budget(db, user_id: int) -> dict:
    """Check if user has remaining token budget. Returns budget info or raises HTTPException."""
    plan = _get_user_plan(db, user_id)
    usage = _get_daily_usage(db, user_id)

    if plan == "ilimitado":
        return {
            "plan": plan,
            "tokens_used": usage["tokens_used"],
            "tokens_limit": None,
            "tokens_remaining": None,
            "requests_today": usage["requests_count"],
        }

    tokens_remaining = DAILY_TOKEN_LIMIT_FREE - usage["tokens_used"]
    if tokens_remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Limite diário de tokens atingido.",
                "tokens_used": usage["tokens_used"],
                "tokens_limit": DAILY_TOKEN_LIMIT_FREE,
                "reset": "meia-noite",
                "dica": "Atualize para o plano ilimitado para uso sem restrições.",
            },
        )

    return {
        "plan": plan,
        "tokens_used": usage["tokens_used"],
        "tokens_limit": DAILY_TOKEN_LIMIT_FREE,
        "tokens_remaining": tokens_remaining,
        "requests_today": usage["requests_count"],
    }


def _record_usage(db, user_id: int, tokens: int, tipo: str, pergunta: str, resposta: str):
    """Record token usage and conversation."""
    today = _get_today_str()
    now = datetime.now().isoformat()

    # Upsert ai_usage
    db.execute(
        """INSERT INTO ai_usage (user_id, data, tokens_used, requests_count)
           VALUES (?, ?, ?, 1)
           ON CONFLICT(user_id, data) DO UPDATE SET
             tokens_used = tokens_used + ?,
             requests_count = requests_count + 1""",
        (user_id, today, tokens, tokens),
    )

    # Insert conversation record
    db.execute(
        """INSERT INTO ai_conversations (user_id, tipo, pergunta, resposta, tokens, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (user_id, tipo, pergunta, resposta, tokens, now),
    )

    db.commit()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="", tags=["AI Tutor"])


@router.post("/api/ai/explain-error")
def explain_error(
    body: ExplainErrorRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Explain why user got a question wrong using the Socratic method."""
    budget = _check_budget(db, user_id)

    # Build question context
    if body.questao_id:
        row = db.execute(
            "SELECT enunciado, resposta_correta, explicacao FROM questoes WHERE id = ?",
            (body.questao_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Questão não encontrada.")
        enunciado = row[0]
        resposta_correta = row[1]
        explicacao = row[2] or ""
        resposta_usuario = body.resposta_usuario or "não informada"
    else:
        if not body.enunciado or not body.resposta_correta:
            raise HTTPException(
                status_code=422,
                detail="Informe questao_id ou enunciado + resposta_correta.",
            )
        enunciado = body.enunciado
        resposta_correta = body.resposta_correta
        explicacao = body.explicacao or ""
        resposta_usuario = body.resposta_usuario or "não informada"

    user_message = (
        f"Questão: {enunciado}\n"
        f"Resposta do aluno: {resposta_usuario}\n"
        f"Resposta correta: {resposta_correta}\n"
        f"Explicação oficial: {explicacao}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS["explain_error"]},
        {"role": "user", "content": user_message},
    ]

    log.info(f"[AI] explain-error user={user_id}")
    text, tokens = call_llm_sync(messages, max_tokens=1500)
    _record_usage(db, user_id, tokens, "explain_error", enunciado[:200], text[:500])

    updated_usage = _get_daily_usage(db, user_id)
    return {
        "resposta": text,
        "tokens_usados": tokens,
        "uso_diario": updated_usage,
        "budget": budget,
    }


@router.post("/api/ai/generate-flashcards")
def generate_flashcards(
    body: GenerateFlashcardsRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Generate flashcards from a topic or text."""
    budget = _check_budget(db, user_id)

    user_message = f"Crie {body.quantidade} flashcards sobre: {body.topico}"
    if body.materia:
        user_message += f"\nMatéria: {body.materia}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS["generate_flashcards"]},
        {"role": "user", "content": user_message},
    ]

    log.info(f"[AI] generate-flashcards user={user_id} topico={body.topico[:50]}")
    text, tokens = call_llm_sync(messages, max_tokens=2000)
    _record_usage(db, user_id, tokens, "generate_flashcards", body.topico[:200], text[:500])

    # Try to parse JSON from response
    flashcards = None
    try:
        # Handle cases where LLM wraps JSON in markdown code block
        clean_text = text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.split("\n")
            # Remove first and last lines (``` markers)
            clean_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        flashcards = json.loads(clean_text)
    except (json.JSONDecodeError, ValueError):
        log.warning(f"[AI] Could not parse flashcards JSON for user={user_id}")

    # Optionally save flashcards to database
    if body.salvar and flashcards:
        for fc in flashcards:
            try:
                db.execute(
                    """INSERT INTO flashcards (user_id, pergunta, resposta, materia, created_at)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        fc.get("pergunta", ""),
                        fc.get("resposta", ""),
                        body.materia or body.topico,
                        datetime.now().isoformat(),
                    ),
                )
            except Exception as e:
                log.warning(f"[AI] Error saving flashcard: {e}")
        db.commit()

    updated_usage = _get_daily_usage(db, user_id)
    return {
        "resposta": text,
        "flashcards": flashcards,
        "tokens_usados": tokens,
        "uso_diario": updated_usage,
        "budget": budget,
        "salvo": body.salvar and flashcards is not None,
    }


@router.post("/api/ai/simplify")
def simplify_text(
    body: SimplifyRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Simplify legal/technical text into plain language."""
    budget = _check_budget(db, user_id)

    if not body.texto.strip():
        raise HTTPException(status_code=422, detail="Texto não pode ser vazio.")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS["simplify_law"]},
        {"role": "user", "content": body.texto},
    ]

    log.info(f"[AI] simplify user={user_id} len={len(body.texto)}")
    text, tokens = call_llm_sync(messages, max_tokens=1500)
    _record_usage(db, user_id, tokens, "simplify", body.texto[:200], text[:500])

    updated_usage = _get_daily_usage(db, user_id)
    return {
        "resposta": text,
        "tokens_usados": tokens,
        "uso_diario": updated_usage,
        "budget": budget,
    }


@router.post("/api/ai/feynman-check")
def feynman_check(
    body: FeynmanCheckRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Check user's Feynman explanation for accuracy and completeness."""
    budget = _check_budget(db, user_id)

    user_message = (
        f"Tópico: {body.topico}\n\n"
        f"Explicação do aluno:\n{body.explicacao}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS["feynman_check"]},
        {"role": "user", "content": user_message},
    ]

    log.info(f"[AI] feynman-check user={user_id} topico={body.topico[:50]}")
    text, tokens = call_llm_sync(messages, max_tokens=1500)
    _record_usage(db, user_id, tokens, "feynman_check", body.topico[:200], text[:500])

    updated_usage = _get_daily_usage(db, user_id)
    return {
        "resposta": text,
        "tokens_usados": tokens,
        "uso_diario": updated_usage,
        "budget": budget,
    }


@router.post("/api/ai/generate-questions")
def generate_questions(
    body: GenerateQuestionsRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Generate practice questions for a topic."""
    budget = _check_budget(db, user_id)

    user_message = (
        f"Crie {body.quantidade} questões sobre: {body.topico}\n"
        f"Estilo: {body.estilo.upper()}"
    )
    if body.materia:
        user_message += f"\nMatéria: {body.materia}"

    messages = [
        {"role": "system", "content": SYSTEM_PROMPTS["generate_questions"]},
        {"role": "user", "content": user_message},
    ]

    log.info(f"[AI] generate-questions user={user_id} topico={body.topico[:50]}")
    text, tokens = call_llm_sync(messages, max_tokens=3000)
    _record_usage(db, user_id, tokens, "generate_questions", body.topico[:200], text[:500])

    # Try to parse JSON from response
    questoes = None
    try:
        clean_text = text.strip()
        if clean_text.startswith("```"):
            lines = clean_text.split("\n")
            clean_text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        questoes = json.loads(clean_text)
    except (json.JSONDecodeError, ValueError):
        log.warning(f"[AI] Could not parse questions JSON for user={user_id}")

    # Optionally save questions to database
    if body.salvar and questoes:
        for q in questoes:
            try:
                db.execute(
                    """INSERT INTO questoes (user_id, enunciado, alternativa_a, alternativa_b,
                       alternativa_c, alternativa_d, alternativa_e, resposta_correta,
                       explicacao, materia, origem, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        user_id,
                        q.get("enunciado", ""),
                        q.get("alternativa_a", ""),
                        q.get("alternativa_b", ""),
                        q.get("alternativa_c", ""),
                        q.get("alternativa_d", ""),
                        q.get("alternativa_e", ""),
                        q.get("resposta_correta", ""),
                        q.get("explicacao", ""),
                        body.materia or body.topico,
                        "ai_generated",
                        datetime.now().isoformat(),
                    ),
                )
            except Exception as e:
                log.warning(f"[AI] Error saving question: {e}")
        db.commit()

    updated_usage = _get_daily_usage(db, user_id)
    return {
        "resposta": text,
        "questoes": questoes,
        "tokens_usados": tokens,
        "uso_diario": updated_usage,
        "budget": budget,
        "salvo": body.salvar and questoes is not None,
    }


@router.post("/api/ai/chat")
def ai_chat(
    body: AIChatRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Free-form chat with the AI tutor about study topics."""
    budget = _check_budget(db, user_id)

    if not body.mensagem.strip():
        raise HTTPException(status_code=422, detail="Mensagem não pode ser vazia.")

    system_content = SYSTEM_PROMPTS["study_tips"]
    user_message = body.mensagem
    if body.contexto:
        user_message = f"Contexto: {body.contexto}\n\nPergunta: {body.mensagem}"

    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": user_message},
    ]

    log.info(f"[AI] chat user={user_id} len={len(body.mensagem)}")
    text, tokens = call_llm_sync(messages, max_tokens=1500)
    _record_usage(db, user_id, tokens, "chat", body.mensagem[:200], text[:500])

    updated_usage = _get_daily_usage(db, user_id)
    return {
        "resposta": text,
        "tokens_usados": tokens,
        "uso_diario": updated_usage,
        "budget": budget,
    }


@router.get("/api/ai/usage")
def get_ai_usage(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Get user's AI token usage for today."""
    plan = _get_user_plan(db, user_id)
    usage = _get_daily_usage(db, user_id)

    limit = None if plan == "ilimitado" else DAILY_TOKEN_LIMIT_FREE
    remaining = None if plan == "ilimitado" else max(0, DAILY_TOKEN_LIMIT_FREE - usage["tokens_used"])

    return {
        "plan": plan,
        "data": _get_today_str(),
        "tokens_used": usage["tokens_used"],
        "tokens_limit": limit,
        "tokens_remaining": remaining,
        "requests_today": usage["requests_count"],
    }


@router.get("/api/ai/history")
def get_ai_history(
    limit: int = Query(default=20, ge=1, le=100),
    tipo: Optional[str] = Query(default=None),
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Get user's AI conversation history."""
    if tipo:
        rows = db.execute(
            """SELECT id, tipo, pergunta, resposta, tokens, created_at
               FROM ai_conversations
               WHERE user_id = ? AND tipo = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, tipo, limit),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT id, tipo, pergunta, resposta, tokens, created_at
               FROM ai_conversations
               WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()

    history = [
        {
            "id": row[0],
            "tipo": row[1],
            "pergunta": row[2],
            "resposta": row[3],
            "tokens": row[4],
            "created_at": row[5],
        }
        for row in rows
    ]

    return {"historico": history, "total": len(history)}


@router.get("/api/ai/status")
def get_ai_status(
    user_id: int = Depends(get_user_id),
):
    """Check if AI is available and which provider is configured."""
    config = _get_ai_config()
    has_openai = bool(config["api_key"])
    ollama_available = False

    if not has_openai:
        # Check if Ollama is reachable
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{config['ollama_url']}/api/tags")
                ollama_available = resp.status_code == 200
        except Exception:
            ollama_available = False

    available = has_openai or ollama_available

    return {
        "disponivel": available,
        "provider": "openai" if has_openai else ("ollama" if ollama_available else None),
        "modelo": config["model"],
        "ollama_url": config["ollama_url"] if not has_openai else None,
        "mensagem": (
            None
            if available
            else "AI não configurada. Defina OPENAI_API_KEY ou inicie o Ollama."
        ),
    }

"""
AI Tutor Router - ConcurseiroOS
Integrates with OpenAI API (GPT-4o-mini) or local Ollama for AI-powered study assistance.
"""

import json
import os
from datetime import date, datetime

import httpx
from deps import get_user_id
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from database import get_db_session
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

    "study_tips": """Você é um tutor de estudos especialista em concursos públicos brasileiros.

COMO RESPONDER:
- Vá direto ao ponto. Evite introduções longas e "enrolação motivacional".
- Estruture a resposta em Markdown para ficar fácil de ler:
  - Use `##` ou `###` para títulos de seções (não use `#`).
  - Use **negrito** para os termos-chave e conceitos principais.
  - Use listas numeradas (1. 2. 3.) ou com marcadores (- item) para enumerar.
  - Use `>` para destacar um macete ou regra de ouro.
  - Use `código` inline para artigos de lei (ex: `art. 189 CC`).
- Seja conciso: respostas de 4 a 12 linhas na maioria dos casos. Aprofunde só se pedirem.
- Quando comparar conceitos, prefira uma estrutura clara (ex: um bloco por conceito + um resumo final).
- Termine com um macete curto ou um "resumão" de 1 linha quando fizer sentido.
- Cite legislação/súmulas quando relevante, de forma objetiva.
- Tom: professor experiente, acessível e objetivo. No máximo 1 emoji por resposta.""",

    "resumo_pdf": """Você é um professor especialista em concursos públicos que cria resumos de estudo a partir de material didático.

A partir do TRECHO de material fornecido, produza um resumo em Markdown otimizado para memorização, seguindo técnicas científicas de estudo:
- Comece com um `## Resumo` de 2-4 linhas com a ideia central.
- Liste os **conceitos-chave** em tópicos, cada um com uma explicação curta (1-2 linhas).
- Destaque em **negrito** os termos que mais caem em prova.
- Quando houver classificações/listas, use estrutura clara (numeração ou marcadores).
- Cite artigos de lei/súmulas com `código` inline quando aparecerem no trecho.
- Termine com `> Macete:` — uma regra de ouro ou mnemônico curto para fixar.
- Seja fiel ao conteúdo do trecho; NÃO invente informação que não esteja nele.
- Se o trecho for questões de prova (e não teoria), resuma os PONTOS TEÓRICOS cobrados, não as questões em si.""",

    "flashcards_pdf": """Você é um especialista em criar flashcards de alta retenção para concursos, aplicando técnicas científicas de aprendizagem (retrieval practice + elaborative interrogation).
A partir do TRECHO fornecido, crie flashcards no formato JSON: [{"pergunta": "...", "resposta": "..."}]
Regras baseadas em evidência:
- Cada flashcard testa UM único conceito (atomic). Evite perguntas com múltiplas respostas.
- Prefira perguntas de RECUPERAÇÃO ATIVA ("O que é...", "Qual a diferença entre...", "Quando se aplica...") em vez de reconhecimento.
- Inclua ao menos 1 flashcard de "por quê/como" (elaborative interrogation) quando o trecho permitir.
- Respostas concisas (máx 2 frases), com o termo-chave explícito.
- Seja fiel ao TRECHO; não invente. Foque nos pontos com maior chance de cair em prova.""",

    "questoes_pdf": """Você é um elaborador de questões de concurso (estilo CESPE/CEBRASPE e FCC) que aplica dificuldade desejável (desirable difficulty) e análise de distratores.
A partir do TRECHO fornecido, crie questões de múltipla escolha (A-E) no formato JSON:
[{"enunciado": "...", "alternativa_a": "...", "alternativa_b": "...", "alternativa_c": "...", "alternativa_d": "...", "alternativa_e": "...", "resposta_correta": "A", "explicacao": "..."}]
Regras baseadas em evidência:
- Enunciados claros; cobre COMPREENSÃO e APLICAÇÃO, não apenas memorização literal.
- Distratores PLAUSÍVEIS (erros conceituais comuns), não absurdos — isso torna o teste diagnóstico.
- Uma única alternativa correta, fiel ao TRECHO.
- A explicação deve dizer por que a correta está certa E por que o distrator mais provável está errado (efeito de hipercorreção).
- Não invente fatos fora do TRECHO.""",
}

# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class ExplainErrorRequest(BaseModel):
    questao_id: int | None = None
    enunciado: str | None = None
    resposta_usuario: str | None = None
    resposta_correta: str | None = None
    explicacao: str | None = None


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


class AnalisarPdfRequest(BaseModel):
    pdf_path: str
    acao: str = Field(default="resumo")  # resumo | flashcards | questoes
    pagina_inicial: int = Field(default=1, ge=1)
    pagina_final: int | None = Field(default=None, ge=1)
    materia: str = ""
    quantidade: int = Field(default=5, ge=1, le=20)
    salvar: bool = False


# ---------------------------------------------------------------------------
# LLM Integration — Multi-Provider (synchronous httpx)
# Supported: OpenAI, Gemini, Kimi (Moonshot), GLM (ZhipuAI), Amazon Bedrock, Ollama
# ---------------------------------------------------------------------------

# Provider configurations: (base_url, default_model, auth_header_format)
PROVIDERS = {
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "format": "openai",
    },
    "claude": {
        "url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-3-5-sonnet-20241022",
        "env_key": "ANTHROPIC_API_KEY",
        "format": "anthropic",  # Anthropic Messages API
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "default_model": "gemini-3.6-flash",
        "env_key": "GEMINI_API_KEY",
        "format": "openai",  # Gemini supports OpenAI-compatible format
    },
    "grok": {
        "url": "https://api.x.ai/v1/chat/completions",
        "default_model": "grok-2",
        "env_key": "XAI_API_KEY",
        "format": "openai",  # xAI Grok is OpenAI-compatible
    },
    "deepseek": {
        "url": "https://api.deepseek.com/chat/completions",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "format": "openai",  # DeepSeek is OpenAI-compatible
    },
    "mistral": {
        "url": "https://api.mistral.ai/v1/chat/completions",
        "default_model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "format": "openai",  # Mistral is OpenAI-compatible
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "llama-3.1-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "format": "openai",  # Groq is OpenAI-compatible (fast inference)
    },
    "together": {
        "url": "https://api.together.xyz/v1/chat/completions",
        "default_model": "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo",
        "env_key": "TOGETHER_API_KEY",
        "format": "openai",  # Together AI is OpenAI-compatible
    },
    "cohere": {
        "url": "https://api.cohere.com/v2/chat",
        "default_model": "command-r-plus",
        "env_key": "COHERE_API_KEY",
        "format": "cohere",  # Cohere has its own format
    },
    "perplexity": {
        "url": "https://api.perplexity.ai/chat/completions",
        "default_model": "llama-3.1-sonar-large-128k-online",
        "env_key": "PERPLEXITY_API_KEY",
        "format": "openai",  # Perplexity is OpenAI-compatible
    },
    "kimi": {
        "url": "https://api.moonshot.cn/v1/chat/completions",
        "default_model": "moonshot-v1-8k",
        "env_key": "KIMI_API_KEY",
        "format": "openai",  # Kimi/Moonshot is OpenAI-compatible
    },
    "glm": {
        "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "default_model": "glm-4.5-flash",  # glm-4-flash foi descontinuado (erro 1211); glm-4.5-flash é o modelo leve/gratuito atual da Zhipu
        "env_key": "GLM_API_KEY",
        "format": "openai",  # ZhipuAI GLM is OpenAI-compatible
    },
    "bedrock": {
        "url": "",  # Uses boto3, not httpx
        "default_model": "anthropic.claude-3-haiku-20240307-v1:0",
        "env_key": "AWS_BEDROCK_REGION",
        "format": "bedrock",
    },
    "ollama": {
        "url": "http://localhost:11434/api/chat",
        "default_model": "llama3.1",
        "env_key": "",
        "format": "ollama",
    },
}


def _get_ai_config() -> dict:
    """Detect the best available AI provider and return configuration.
    Priority: 1) env var AI_PROVIDER override, 2) user DB config (ai_config table), 3) auto-detect from env keys.
    """
    provider_override = os.environ.get("AI_PROVIDER", "auto")
    model_override = os.environ.get("AI_MODEL", "")

    # If user specified a provider via env, use it directly
    if provider_override != "auto" and provider_override in PROVIDERS:
        prov = PROVIDERS[provider_override]
        api_key = os.environ.get(prov["env_key"], "") if prov["env_key"] else ""
        # Fallback: if env key is empty, try DB config for same provider
        if not api_key:
            try:
                import sqlite3 as _sql

                from settings import settings as _settings
                _conn = _sql.connect(_settings.DB_PATH, check_same_thread=False, timeout=5)
                _conn.row_factory = _sql.Row
                _row = _conn.execute("SELECT api_key FROM ai_config WHERE user_id = 1 AND provider = ?", (provider_override,)).fetchone()
                _conn.close()
                if _row and _row["api_key"]:
                    api_key = _row["api_key"]
            except Exception:
                pass
        return {
            "provider": provider_override,
            "api_key": api_key,
            "url": prov["url"] if provider_override != "ollama" else os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat",
            "model": model_override or prov["default_model"],
            "format": prov["format"],
        }

    # Check user DB config (ai_config table)
    try:
        import sqlite3

        from settings import settings
        conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False, timeout=5)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT provider, api_key, model FROM ai_config WHERE user_id = 1").fetchone()
        conn.close()
        if row and row["provider"] and row["provider"] != "auto" and row["api_key"]:
            db_provider = row["provider"]
            db_key = row["api_key"]
            db_model = row["model"]
            if db_provider in PROVIDERS:
                prov = PROVIDERS[db_provider]
                url = prov["url"]
                if db_provider == "ollama":
                    url = db_key if db_key.startswith("http") else os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat"
                return {
                    "provider": db_provider,
                    "api_key": db_key,
                    "url": url,
                    "model": model_override or db_model or prov["default_model"],
                    "format": prov["format"],
                }
    except Exception:
        pass

    # Auto-detect: try providers in priority order (from env keys)
    priority = ["openai", "claude", "gemini", "grok", "deepseek", "mistral", "groq", "together", "cohere", "perplexity", "kimi", "glm", "bedrock", "ollama"]
    for name in priority:
        prov = PROVIDERS[name]
        if prov["env_key"]:
            key = os.environ.get(prov["env_key"], "")
            if key:
                url = prov["url"]
                if name == "ollama":
                    url = os.environ.get("OLLAMA_URL", "http://localhost:11434") + "/api/chat"
                return {
                    "provider": name,
                    "api_key": key,
                    "url": url,
                    "model": model_override or prov["default_model"],
                    "format": prov["format"],
                }
        elif name == "ollama":
            # Ollama doesn't need API key, try if URL is reachable
            ollama_url = os.environ.get("OLLAMA_URL", "http://localhost:11434")
            return {
                "provider": "ollama",
                "api_key": "",
                "url": f"{ollama_url}/api/chat",
                "model": model_override or prov["default_model"],
                "format": "ollama",
            }

    return {"provider": "none", "api_key": "", "url": "", "model": "", "format": ""}


def _traduzir_erro_provedor(provider: str, status_code: int, corpo: str) -> tuple[int, str]:
    """Converte um erro HTTP do provedor de IA em (status, mensagem) claros em pt-BR.

    Muitos provedores (GLM/Zhipu, OpenAI, etc.) retornam a causa real no corpo
    JSON (ex.: saldo insuficiente, modelo inexistente, key inválida). Sem isto, o
    backend devolvia um 502 genérico "Erro na API glm: 429", escondendo o motivo.

    Returns:
        (status_code_para_o_cliente, mensagem_amigavel)
    """
    import json as _json

    label = provider.upper()

    # Tentar extrair a mensagem/código do corpo JSON do provedor
    prov_msg = ""
    prov_code = ""
    try:
        parsed = _json.loads(corpo)
        err = parsed.get("error", parsed) if isinstance(parsed, dict) else {}
        if isinstance(err, dict):
            prov_msg = str(err.get("message", "") or "")
            prov_code = str(err.get("code", "") or "")
        elif isinstance(err, str):
            prov_msg = err
    except Exception:
        prov_msg = ""

    texto = f"{prov_code} {prov_msg} {corpo}".lower()

    # Saldo/recurso insuficiente (GLM code 1113, ou termos comuns)
    if (
        "1113" in texto
        or "余额不足" in texto  # saldo insuficiente
        or ("insufficient" in texto and ("balance" in texto or "quota" in texto or "credit" in texto))
        or "billing" in texto
    ):
        return 402, (
            f"{label}: saldo insuficiente ou sem pacote de recursos na sua conta. "
            f"Recarregue ou ative um pacote no painel do provedor e tente novamente."
        )

    # Modelo inexistente/inválido (GLM code 1211)
    if "1211" in texto or "模型不存在" in texto or ("model" in texto and ("not exist" in texto or "not found" in texto or "does not exist" in texto)):
        return 400, (
            f"{label}: o modelo configurado não existe. Verifique o nome do modelo "
            f"na configuração de IA (ex.: para GLM use 'glm-4.5-flash')."
        )

    # API key inválida / não autorizada
    if status_code in (401, 403) or "invalid api key" in texto or "unauthorized" in texto or "认证" in texto:
        return 401, f"{label}: API key inválida ou sem permissão. Verifique a chave configurada."

    # Rate limit (sem indício de saldo)
    if status_code == 429:
        return 429, f"{label}: limite de requisições atingido (rate limit). Aguarde alguns instantes e tente novamente."

    # Fallback: repassa a mensagem do provedor se houver, senão o status
    if prov_msg:
        return 502, f"Erro na API {provider}: {prov_msg[:160]}"
    return 502, f"Erro na API {provider}: {status_code}"


def call_llm_sync(messages: list[dict], max_tokens: int = 1000) -> tuple[str, int]:
    """Call LLM synchronously via the detected provider. Returns (response_text, tokens_used)."""
    config = _get_ai_config()
    provider = config["provider"]
    api_key = config["api_key"]
    url = config["url"]
    model = config["model"]
    fmt = config["format"]

    if provider == "none":
        raise HTTPException(
            status_code=503,
            detail="AI não disponível. Configure uma das chaves: OPENAI_API_KEY, GEMINI_API_KEY, KIMI_API_KEY, GLM_API_KEY, AWS_BEDROCK_REGION, ou inicie o Ollama.",
        )

    # --- OpenAI-compatible format (OpenAI, Gemini, Grok, DeepSeek, Mistral, Groq, Together, Perplexity, Kimi, GLM) ---
    if fmt == "openai":
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }

            with httpx.Client(timeout=45) as client:
                response = client.post(
                    url,
                    headers=headers,
                    json={
                        "model": model,
                        "messages": messages,
                        "max_tokens": max_tokens,
                        "temperature": 0.7,
                    },
                )
                response.raise_for_status()
                data = response.json()
                try:
                    text = data["choices"][0]["message"]["content"]
                except (KeyError, IndexError, TypeError):
                    # Gemini sometimes returns different structure or empty response
                    log.warning(f"[AI:{provider}] Unexpected response format: {str(data)[:300]}")
                    text = data.get("choices", [{}])[0].get("message", {}).get("content") or str(data.get("error", "Resposta vazia do modelo"))
                tokens = data.get("usage", {}).get("total_tokens", len(text) // 3)
                return text, tokens
        except httpx.HTTPStatusError as e:
            log.error(f"[AI:{provider}] HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            status, msg = _traduzir_erro_provedor(provider, e.response.status_code, e.response.text)
            raise HTTPException(status_code=status, detail=msg) from e
        except httpx.RequestError as e:
            log.error(f"[AI:{provider}] Request error: {e}")
            raise HTTPException(
                status_code=503,
                detail=f"Não foi possível conectar ao {provider}.",
            )

    # --- Anthropic Claude (Messages API) ---
    elif fmt == "anthropic":
        try:
            # Extract system message
            system_msg = ""
            user_msgs = []
            for msg in messages:
                if msg["role"] == "system":
                    system_msg = msg["content"]
                else:
                    user_msgs.append({"role": msg["role"], "content": msg["content"]})

            headers = {
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
            body = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": user_msgs,
                "temperature": 0.7,
            }
            if system_msg:
                body["system"] = system_msg

            with httpx.Client(timeout=45) as client:
                response = client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
                text = data["content"][0]["text"]
                tokens = data.get("usage", {}).get("input_tokens", 0) + data.get("usage", {}).get("output_tokens", 0)
                return text, tokens
        except httpx.HTTPStatusError as e:
            log.error(f"[AI:claude] HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            status, msg = _traduzir_erro_provedor("claude", e.response.status_code, e.response.text)
            raise HTTPException(status_code=status, detail=msg) from e
        except httpx.RequestError as e:
            log.error(f"[AI:claude] Request error: {e}")
            raise HTTPException(status_code=503, detail="Não foi possível conectar à API Anthropic.")

    # --- Cohere (Chat API v2) ---
    elif fmt == "cohere":
        try:
            # Convert messages format
            system_msg = ""
            chat_history = []
            user_message = ""
            for msg in messages:
                if msg["role"] == "system":
                    system_msg = msg["content"]
                elif msg["role"] == "user":
                    user_message = msg["content"]
                elif msg["role"] == "assistant":
                    chat_history.append({"role": "assistant", "content": msg["content"]})

            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            body = {
                "model": model,
                "messages": [{"role": "system", "content": system_msg}] + [{"role": "user", "content": user_message}] if system_msg else [{"role": "user", "content": user_message}],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            }

            with httpx.Client(timeout=45) as client:
                response = client.post(url, headers=headers, json=body)
                response.raise_for_status()
                data = response.json()
                text = data.get("message", {}).get("content", [{}])[0].get("text", "")
                tokens = data.get("usage", {}).get("billed_units", {}).get("input_tokens", 0) + data.get("usage", {}).get("billed_units", {}).get("output_tokens", 0)
                return text, tokens or len(text) // 3
        except httpx.HTTPStatusError as e:
            log.error(f"[AI:cohere] HTTP error: {e.response.status_code} - {e.response.text[:200]}")
            status, msg = _traduzir_erro_provedor("cohere", e.response.status_code, e.response.text)
            raise HTTPException(status_code=status, detail=msg) from e
        except httpx.RequestError as e:
            log.error(f"[AI:cohere] Request error: {e}")
            raise HTTPException(status_code=503, detail="Não foi possível conectar à API Cohere.")

    # --- Amazon Bedrock ---
    elif fmt == "bedrock":
        try:
            import boto3

            region = os.environ.get("AWS_BEDROCK_REGION", "us-east-1")
            bedrock = boto3.client("bedrock-runtime", region_name=region)

            # Convert messages to Bedrock format
            system_msg = ""
            user_msgs = []
            for msg in messages:
                if msg["role"] == "system":
                    system_msg = msg["content"]
                else:
                    user_msgs.append({"role": msg["role"], "content": [{"text": msg["content"]}]})

            body = {
                "messages": user_msgs,
                "max_tokens": max_tokens,
                "temperature": 0.7,
            }
            if system_msg:
                body["system"] = [{"text": system_msg}]

            response = bedrock.converse(
                modelId=model,
                messages=user_msgs,
                system=[{"text": system_msg}] if system_msg else [],
                inferenceConfig={"maxTokens": max_tokens, "temperature": 0.7},
            )
            text = response["output"]["message"]["content"][0]["text"]
            tokens = response.get("usage", {}).get("totalTokens", len(text) // 3)
            return text, tokens
        except ImportError:
            raise HTTPException(
                status_code=503,
                detail="boto3 não instalado. Instale com: pip install boto3",
            )
        except Exception as e:
            log.error(f"[AI:bedrock] Error: {e}")
            raise HTTPException(status_code=502, detail=f"Erro no Amazon Bedrock: {str(e)[:100]}")

    # --- Ollama (local) ---
    elif fmt == "ollama":
        try:
            with httpx.Client(timeout=120) as client:
                response = client.post(
                    url,
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
            log.error(f"[AI:ollama] Error: {e}")
            raise HTTPException(
                status_code=503,
                detail="Ollama não está rodando. Inicie com: ollama serve",
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


def _get_user_token_limit(db, user_id: int) -> int:
    """Retorna o override de limite diário de tokens do usuário.

    0 → sem override (usa default do plano). >0 → limite custom. -1 → ilimitado.
    """
    try:
        row = db.execute("SELECT ai_token_limit FROM users WHERE id = ?", (user_id,)).fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        pass
    return 0


def _check_budget(db, user_id: int) -> dict:
    """Check if user has remaining token budget. Returns budget info or raises HTTPException."""
    plan = _get_user_plan(db, user_id)
    usage = _get_daily_usage(db, user_id)
    override = _get_user_token_limit(db, user_id)

    # Override por usuário tem prioridade: -1 = ilimitado, >0 = limite custom
    if override == -1:
        return {
            "plan": plan, "tokens_used": usage["tokens_used"], "tokens_limit": None,
            "tokens_remaining": None, "requests_today": usage["requests_count"],
        }

    if plan == "ilimitado" and override == 0:
        return {
            "plan": plan,
            "tokens_used": usage["tokens_used"],
            "tokens_limit": None,
            "tokens_remaining": None,
            "requests_today": usage["requests_count"],
        }

    limite = override if override > 0 else DAILY_TOKEN_LIMIT_FREE
    tokens_remaining = limite - usage["tokens_used"]
    if tokens_remaining <= 0:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Limite diário de tokens atingido.",
                "tokens_used": usage["tokens_used"],
                "tokens_limit": limite,
                "reset": "meia-noite",
                "dica": "Atualize para o plano ilimitado para uso sem restrições.",
            },
        )

    return {
        "plan": plan,
        "tokens_used": usage["tokens_used"],
        "tokens_limit": limite,
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
            if not isinstance(fc, dict):
                continue
            pergunta = (fc.get("pergunta") or "").strip()
            resposta = (fc.get("resposta") or "").strip()
            if not pergunta or not resposta:
                continue
            try:
                db.execute(
                    """INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id)
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        pergunta,
                        resposta,
                        _get_today_str(),
                        body.materia or body.topico,
                        user_id,
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
        materia_q = body.materia or body.topico
        for q in questoes:
            if not isinstance(q, dict):
                continue
            enunciado = (q.get("enunciado") or "").strip()
            if len(enunciado) < 10:
                continue
            try:
                db.execute(
                    """INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                        alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao,
                        dificuldade, banca, prova_origem, created_at, user_id)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        materia_q,
                        "",
                        enunciado,
                        (q.get("alternativa_a") or "").strip(),
                        (q.get("alternativa_b") or "").strip(),
                        (q.get("alternativa_c") or "").strip(),
                        (q.get("alternativa_d") or "").strip(),
                        (q.get("alternativa_e") or "").strip(),
                        (q.get("resposta_correta") or "").strip().upper(),
                        (q.get("explicacao") or "").strip(),
                        "Médio",
                        "IA",
                        f"IA: {body.topico}"[:200],
                        _get_today_str(),
                        user_id,
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
    tipo: str | None = Query(default=None),
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
    provider = config["provider"]
    available = provider != "none"

    # Check Ollama reachability if it's the selected provider
    if provider == "ollama":
        try:
            ollama_base = os.environ.get("OLLAMA_URL", "http://localhost:11434")
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{ollama_base}/api/tags")
                available = resp.status_code == 200
        except Exception:
            available = False

    # List all configured providers
    configured_providers = []
    for name, prov in PROVIDERS.items():
        if prov["env_key"] and os.environ.get(prov["env_key"], ""):
            configured_providers.append(name)
        elif name == "ollama":
            configured_providers.append("ollama (local)")

    provider_labels = {
        "openai": "OpenAI (GPT)",
        "claude": "Anthropic Claude",
        "gemini": "Google Gemini",
        "grok": "xAI Grok",
        "deepseek": "DeepSeek",
        "mistral": "Mistral AI",
        "groq": "Groq (fast inference)",
        "together": "Together AI",
        "cohere": "Cohere Command",
        "perplexity": "Perplexity AI",
        "kimi": "Kimi (Moonshot AI)",
        "glm": "GLM (ZhipuAI / ChatGLM)",
        "bedrock": "Amazon Bedrock",
        "ollama": "Ollama (local)",
    }

    return {
        "disponivel": available,
        "provider": provider,
        "provider_label": provider_labels.get(provider, provider),
        "modelo": config["model"],
        "providers_configurados": configured_providers,
        "providers_suportados": list(PROVIDERS.keys()),
        "mensagem": (
            None
            if available
            else "AI não configurada. Defina uma das chaves: OPENAI_API_KEY, GEMINI_API_KEY, KIMI_API_KEY, GLM_API_KEY, AWS_BEDROCK_REGION, ou inicie o Ollama."
        ),
    }


# ---------------------------------------------------------------------------
# AI Config Endpoints (per-user provider configuration via UI)
# ---------------------------------------------------------------------------

class AIConfigUpdate(BaseModel):
    provider: str = "auto"
    api_key: str = ""
    model: str = ""


@router.get("/api/ai/config")
def get_ai_config_endpoint(
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Get user's AI provider configuration."""
    try:
        row = db.execute(
            "SELECT provider, api_key, model FROM ai_config WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row:
            key = row[1] or ""
            masked = key[:4] + "..." + key[-4:] if len(key) > 8 else ("***" if key else "")
            return {
                "provider": row[0] or "auto",
                "api_key_masked": masked,
                "model_override": row[2] or "",
                "has_key": bool(key),
            }
    except Exception:
        pass
    return {"provider": "auto", "api_key_masked": "", "model_override": "", "has_key": False}


@router.put("/api/ai/config")
def update_ai_config_endpoint(
    body: AIConfigUpdate,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Save user's AI provider configuration."""
    # Create table if not exists
    db.execute("""
        CREATE TABLE IF NOT EXISTS ai_config (
            user_id INTEGER PRIMARY KEY,
            provider TEXT DEFAULT 'auto',
            api_key TEXT DEFAULT '',
            model TEXT DEFAULT ''
        )
    """)

    # If api_key is empty, preserve existing key
    if not body.api_key:
        existing = db.execute("SELECT api_key FROM ai_config WHERE user_id = ?", (user_id,)).fetchone()
        existing_key = existing[0] if existing else ""
    else:
        existing_key = body.api_key

    db.execute(
        """INSERT INTO ai_config (user_id, provider, api_key, model)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET
             provider = ?, api_key = ?, model = ?""",
        (user_id, body.provider, existing_key, body.model, body.provider, existing_key, body.model),
    )
    db.commit()

    # Apply config to environment for immediate effect
    if body.provider and body.provider != "auto":
        os.environ["AI_PROVIDER"] = body.provider
    elif body.provider == "auto":
        os.environ.pop("AI_PROVIDER", None)

    if body.api_key:
        prov = PROVIDERS.get(body.provider, {})
        env_key = prov.get("env_key", "")
        if env_key:
            os.environ[env_key] = body.api_key

    if body.model:
        os.environ["AI_MODEL"] = body.model

    log.info(f"[AI Config] user={user_id} provider={body.provider} model={body.model or 'default'}")
    return {"ok": True}


@router.post("/api/ai/config/test")
def test_ai_config_endpoint(
    body: AIConfigUpdate,
    user_id: int = Depends(get_user_id),
):
    """Test an AI provider configuration without saving."""
    provider = body.provider or "auto"
    api_key = body.api_key
    model = body.model

    if provider == "auto":
        return {"ok": False, "error": "Selecione um provider para testar."}

    prov = PROVIDERS.get(provider)
    if not prov:
        return {"ok": False, "error": f"Provider '{provider}' não reconhecido."}

    # For Ollama, test connectivity
    if provider == "ollama":
        ollama_url = api_key or "http://localhost:11434"
        try:
            with httpx.Client(timeout=5) as client:
                resp = client.get(f"{ollama_url}/api/tags")
                if resp.status_code == 200:
                    models = [m["name"] for m in resp.json().get("models", [])[:5]]
                    return {"ok": True, "provider_label": "Ollama (local)", "model": model or "llama3.1", "models_available": models}
                return {"ok": False, "error": f"Ollama respondeu {resp.status_code}"}
        except Exception as e:
            return {"ok": False, "error": f"Não foi possível conectar ao Ollama: {str(e)[:80]}"}

    # For Bedrock, just validate region
    if provider == "bedrock":
        region = api_key or "us-east-1"
        if len(region) < 5 or "-" not in region:
            return {"ok": False, "error": "Informe uma região AWS válida (ex: us-east-1)"}
        return {"ok": True, "provider_label": "Amazon Bedrock", "model": model or prov["default_model"]}

    # For API-key providers, make a minimal test call
    if not api_key:
        return {"ok": False, "error": "Informe a API key para testar."}

    test_model = model or prov["default_model"]
    test_messages = [{"role": "user", "content": "Diga apenas 'OK' em uma palavra."}]

    try:
        # Temporarily set env vars for the test
        old_provider = os.environ.get("AI_PROVIDER", "")
        old_key = ""
        env_key = prov.get("env_key", "")
        if env_key:
            old_key = os.environ.get(env_key, "")
            os.environ[env_key] = api_key
        os.environ["AI_PROVIDER"] = provider
        if model:
            old_model = os.environ.get("AI_MODEL", "")
            os.environ["AI_MODEL"] = model

        text, tokens = call_llm_sync(test_messages, max_tokens=10)

        # Restore
        if old_provider:
            os.environ["AI_PROVIDER"] = old_provider
        else:
            os.environ.pop("AI_PROVIDER", None)
        if env_key:
            if old_key:
                os.environ[env_key] = old_key
            else:
                os.environ.pop(env_key, None)
        if model:
            if old_model:
                os.environ["AI_MODEL"] = old_model
            else:
                os.environ.pop("AI_MODEL", None)

        provider_labels = {k: v for k, v in zip(
            PROVIDERS.keys(),
            ["OpenAI", "Anthropic Claude", "Google Gemini", "xAI Grok", "DeepSeek", "Mistral AI", "Groq", "Together AI", "Cohere", "Perplexity", "Kimi", "GLM", "Amazon Bedrock", "Ollama"]
        )}

        return {"ok": True, "provider_label": provider_labels.get(provider, provider), "model": test_model, "response_preview": text[:50], "tokens": tokens}

    except HTTPException as e:
        return {"ok": False, "error": e.detail if isinstance(e.detail, str) else str(e.detail)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:100]}


# ---------------------------------------------------------------------------
# Análise de PDF pela IA — resumo / flashcards / questões a partir de um trecho
# ---------------------------------------------------------------------------

# Limite de caracteres do trecho enviado ao LLM (~1 token ≈ 4 chars).
# ~24k chars ≈ 6k tokens de entrada, seguro para modelos de 8k+ contexto.
_MAX_CHARS_TRECHO_PDF = 24000


def _parse_json_llm(text: str):
    """Extrai o JSON de uma resposta do LLM, tolerando cerca de markdown (```json).

    Retorna o objeto Python parseado ou None se não for possível.
    """
    if not text:
        return None
    clean = text.strip()
    if clean.startswith("```"):
        linhas = clean.split("\n")
        # remove a primeira linha (```json) e a última se for ```
        clean = "\n".join(linhas[1:-1] if linhas[-1].strip() == "```" else linhas[1:])
    try:
        return json.loads(clean)
    except (json.JSONDecodeError, ValueError):
        # Última tentativa: recortar do primeiro '[' ou '{' ao último ']' ou '}'
        for abre, fecha in (("[", "]"), ("{", "}")):
            i, j = clean.find(abre), clean.rfind(fecha)
            if i != -1 and j != -1 and j > i:
                try:
                    return json.loads(clean[i:j + 1])
                except (json.JSONDecodeError, ValueError):
                    pass
        return None


def _resolver_pdf_path(pdf_path: str, conn=None, user_id: int = None) -> str:
    """Resolve o caminho do PDF dentro do PDF_ROOT com proteção anti-traversal.

    Aceita tanto o path relativo da árvore ('Matéria/arquivo.pdf') quanto com
    prefixo '/pdf/'. Levanta HTTPException se inválido ou fora da raiz.

    Se `conn` e `user_id` forem informados, também valida a visibilidade do PDF
    (dono ou compartilhado) — impede que um usuário analise PDF de outro.
    """
    from pathlib import Path

    from routers import pdf as pdf_module

    root = pdf_module.PDF_ROOT
    if not root:
        raise HTTPException(status_code=503, detail="Diretório de PDFs não configurado.")

    rel = (pdf_path or "").strip()
    if rel.startswith("/pdf/"):
        rel = rel[len("/pdf/"):]
    rel = rel.lstrip("/")

    if ".." in rel or not rel:
        raise HTTPException(status_code=400, detail="Caminho de PDF inválido.")

    full = Path(root) / rel
    try:
        full.relative_to(Path(root))
    except ValueError:
        raise HTTPException(status_code=403, detail="Acesso negado ao PDF.") from None

    resolved = full.resolve()
    if not resolved.exists() or resolved.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="PDF não encontrado.")

    # Autorização de visibilidade (dono ou compartilhado) — após confirmar que o
    # arquivo existe, para não confundir "inexistente" (404) com "sem acesso" (403).
    if conn is not None and user_id is not None:
        if not pdf_module.can_access(conn, user_id, rel):
            raise HTTPException(status_code=403, detail="Acesso negado ao PDF.")

    return str(resolved)


@router.post("/api/ai/analisar-pdf")
def analisar_pdf(
    body: AnalisarPdfRequest,
    db=Depends(get_db_session),
    user_id: int = Depends(get_user_id),
):
    """Gera resumo / flashcards / questões a partir de um trecho de um PDF.

    Fase 1a: implementa a ação 'resumo'. Ações 'flashcards' e 'questoes' serão
    adicionadas nas fases seguintes.
    """
    from plans import get_plan, is_feature_enabled_for_plan
    _user_row = db.execute("SELECT plano, plano_expira FROM users WHERE id = ?", (user_id,)).fetchone()
    _user = dict(_user_row) if _user_row else {"plano": "free", "plano_expira": ""}
    _plano = get_plan(_user)
    if not is_feature_enabled_for_plan("ai_tutor", _plano):
        raise HTTPException(status_code=503, detail="Recurso de IA não disponível no seu plano.")

    budget = _check_budget(db, user_id)

    acao = (body.acao or "resumo").strip().lower()
    if acao not in ("resumo", "flashcards", "questoes"):
        raise HTTPException(status_code=422, detail="Ação inválida. Use: resumo, flashcards ou questoes.")

    if body.pagina_final is not None and body.pagina_final < body.pagina_inicial:
        raise HTTPException(status_code=422, detail="Página final deve ser >= página inicial.")

    caminho = _resolver_pdf_path(body.pdf_path, conn=db, user_id=user_id)

    # Extrai apenas o intervalo de páginas pedido (PDFs de matéria são enormes).
    from routers.questoes.importacao import _extrair_texto_pdf_intervalo

    try:
        texto, total_paginas = _extrair_texto_pdf_intervalo(
            caminho, body.pagina_inicial, body.pagina_final
        )
    except Exception as e:
        log.error(f"[AI] Erro ao extrair PDF {body.pdf_path}: {e}")
        raise HTTPException(status_code=400, detail="Não foi possível extrair texto do PDF.") from None

    texto = (texto or "").strip()
    if len(texto) < 50:
        raise HTTPException(
            status_code=400,
            detail="Trecho sem texto suficiente. O PDF pode ser escaneado (sem texto selecionável) ou o intervalo de páginas está vazio.",
        )

    truncado = len(texto) > _MAX_CHARS_TRECHO_PDF
    trecho = texto[:_MAX_CHARS_TRECHO_PDF]

    nome_pdf = body.pdf_path.split("/")[-1].replace(".pdf", "")
    contexto_paginas = f"páginas {body.pagina_inicial}" + (
        f"–{body.pagina_final}" if body.pagina_final else " em diante"
    )

    if acao == "resumo":
        user_message = (
            f"Material: {nome_pdf} ({contexto_paginas})."
            + (f" Matéria: {body.materia}." if body.materia else "")
            + "\n\nTRECHO:\n"
            + trecho
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["resumo_pdf"]},
            {"role": "user", "content": user_message},
        ]
        log.info(f"[AI] analisar-pdf resumo user={user_id} pdf={nome_pdf[:40]} {contexto_paginas}")
        text, tokens = call_llm_sync(messages, max_tokens=1500)
        _record_usage(db, user_id, tokens, "resumo_pdf", f"{nome_pdf} {contexto_paginas}", text[:500])

        updated_usage = _get_daily_usage(db, user_id)
        return {
            "ok": True,
            "acao": "resumo",
            "resumo": text,
            "resposta": text,
            "tecnica": "Distributed Summary + Dual Coding",
            "pdf": nome_pdf,
            "paginas": {"inicial": body.pagina_inicial, "final": body.pagina_final, "total": total_paginas},
            "trecho_truncado": truncado,
            "tokens_usados": tokens,
            "uso_diario": updated_usage,
            "budget": budget,
        }

    if acao == "flashcards":
        user_message = (
            f"A partir do TRECHO do material '{nome_pdf}' ({contexto_paginas}), "
            f"crie {body.quantidade} flashcards de estudo."
            + (f" Matéria: {body.materia}." if body.materia else "")
            + "\n\nTRECHO:\n"
            + trecho
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["flashcards_pdf"]},
            {"role": "user", "content": user_message},
        ]
        log.info(f"[AI] analisar-pdf flashcards user={user_id} pdf={nome_pdf[:40]} {contexto_paginas}")
        text, tokens = call_llm_sync(messages, max_tokens=2000)
        _record_usage(db, user_id, tokens, "flashcards_pdf", f"{nome_pdf} {contexto_paginas}", text[:500])

        flashcards = _parse_json_llm(text)
        if not isinstance(flashcards, list):
            flashcards = None

        salvos = 0
        if body.salvar and flashcards:
            materia_fc = body.materia or nome_pdf
            for fc in flashcards:
                if not isinstance(fc, dict):
                    continue
                pergunta = (fc.get("pergunta") or "").strip()
                resposta = (fc.get("resposta") or "").strip()
                if not pergunta or not resposta:
                    continue
                try:
                    db.execute(
                        """INSERT INTO flashcards (pergunta, resposta, proxima_revisao, materia, user_id)
                           VALUES (?, ?, ?, ?, ?)""",
                        (pergunta, resposta, _get_today_str(), materia_fc, user_id),
                    )
                    salvos += 1
                except Exception as e:
                    log.warning(f"[AI] Erro ao salvar flashcard do PDF: {e}")
            if salvos:
                db.commit()

        updated_usage = _get_daily_usage(db, user_id)
        return {
            "ok": True,
            "acao": "flashcards",
            "flashcards": flashcards,
            "resposta": text,
            "tecnica": "Retrieval Practice + FSRS (revisão espaçada)",
            "pdf": nome_pdf,
            "paginas": {"inicial": body.pagina_inicial, "final": body.pagina_final, "total": total_paginas},
            "trecho_truncado": truncado,
            "salvos": salvos,
            "salvo": body.salvar and salvos > 0,
            "tokens_usados": tokens,
            "uso_diario": updated_usage,
            "budget": budget,
        }

    if acao == "questoes":
        user_message = (
            f"A partir do TRECHO do material '{nome_pdf}' ({contexto_paginas}), "
            f"crie {body.quantidade} questões de múltipla escolha (A-E) no estilo CESPE/FCC."
            + (f" Matéria: {body.materia}." if body.materia else "")
            + "\n\nTRECHO:\n"
            + trecho
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPTS["questoes_pdf"]},
            {"role": "user", "content": user_message},
        ]
        log.info(f"[AI] analisar-pdf questoes user={user_id} pdf={nome_pdf[:40]} {contexto_paginas}")
        text, tokens = call_llm_sync(messages, max_tokens=3000)
        _record_usage(db, user_id, tokens, "questoes_pdf", f"{nome_pdf} {contexto_paginas}", text[:500])

        questoes = _parse_json_llm(text)
        if not isinstance(questoes, list):
            questoes = None

        salvos = 0
        if body.salvar and questoes:
            materia_q = body.materia or nome_pdf
            prova_origem = f"IA: {nome_pdf}"
            for q in questoes:
                if not isinstance(q, dict):
                    continue
                enunciado = (q.get("enunciado") or "").strip()
                if len(enunciado) < 10:
                    continue
                try:
                    db.execute(
                        """INSERT INTO questoes (materia, topico, enunciado, alternativa_a, alternativa_b,
                            alternativa_c, alternativa_d, alternativa_e, resposta_correta, explicacao,
                            dificuldade, banca, prova_origem, created_at, user_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            materia_q,
                            "",
                            enunciado,
                            (q.get("alternativa_a") or "").strip(),
                            (q.get("alternativa_b") or "").strip(),
                            (q.get("alternativa_c") or "").strip(),
                            (q.get("alternativa_d") or "").strip(),
                            (q.get("alternativa_e") or "").strip(),
                            (q.get("resposta_correta") or "").strip().upper(),
                            (q.get("explicacao") or "").strip(),
                            "Médio",
                            "IA",
                            prova_origem,
                            _get_today_str(),
                            user_id,
                        ),
                    )
                    salvos += 1
                except Exception as e:
                    log.warning(f"[AI] Erro ao salvar questão do PDF: {e}")
            if salvos:
                db.commit()

        updated_usage = _get_daily_usage(db, user_id)
        return {
            "ok": True,
            "acao": "questoes",
            "questoes": questoes,
            "resposta": text,
            "tecnica": "Pre-testing + Desirable Difficulty",
            "pdf": nome_pdf,
            "paginas": {"inicial": body.pagina_inicial, "final": body.pagina_final, "total": total_paginas},
            "trecho_truncado": truncado,
            "salvos": salvos,
            "salvo": body.salvar and salvos > 0,
            "tokens_usados": tokens,
            "uso_diario": updated_usage,
            "budget": budget,
        }

    raise HTTPException(status_code=501, detail=f"Ação '{acao}' ainda não implementada.")

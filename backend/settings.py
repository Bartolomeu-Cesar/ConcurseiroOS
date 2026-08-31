"""Configurações centralizadas do ConcurseiroOS."""
import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

# Load .env file automatically (looks in backend/ dir first, then project root)
_BACKEND_DIR_ENV = Path(__file__).parent
_PROJECT_ROOT_ENV = _BACKEND_DIR_ENV.parent

# Priority: backend/.env > project_root/.env
for _env_path in [_BACKEND_DIR_ENV / ".env", _PROJECT_ROOT_ENV / ".env"]:
    if _env_path.exists():
        load_dotenv(_env_path)
        break
else:
    # No .env found — try default dotenv behavior (searches cwd upwards)
    load_dotenv()

_BACKEND_DIR = Path(__file__).parent
_JWT_SECRET_FILE = _BACKEND_DIR / ".jwt_secret"


def _get_jwt_secret() -> str:
    """Obtém JWT_SECRET de forma persistente, garantindo força mínima.

    Ordem de resolução:
    1. Se env var JWT_SECRET está definida, usa ela.
    2. Se arquivo .jwt_secret existe, lê dele.
    3. Senão, gera um novo secret e salva no arquivo.

    Segurança (RFC 7518 §3.2): HMAC-SHA256 exige chave de no mínimo 32 bytes.
    - Segredo vindo de ENV com < 32 bytes: respeitamos a escolha do operador
      (não sobrescrevemos config externa), mas emitimos um aviso claro.
    - Segredo de ARQUIVO com < 32 bytes (legado): regeneramos para 32 bytes,
      eliminando a fraqueza. Isso invalida tokens antigos uma única vez.
    """
    import logging
    log = logging.getLogger("settings")
    MIN_BYTES = 32

    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        if len(env_secret.encode()) < MIN_BYTES:
            log.warning(
                "JWT_SECRET (via env) tem %d bytes — abaixo do mínimo de %d recomendado "
                "para HMAC-SHA256 (RFC 7518 §3.2). Use um segredo mais longo (ex.: "
                "`python -c \"import secrets; print(secrets.token_hex(32))\"`).",
                len(env_secret.encode()), MIN_BYTES,
            )
        return env_secret

    if _JWT_SECRET_FILE.exists():
        file_secret = _JWT_SECRET_FILE.read_text().strip()
        if file_secret and len(file_secret.encode()) >= MIN_BYTES:
            return file_secret
        # Arquivo legado com segredo curto/fraco → regenera para 32 bytes
        log.warning(
            "Arquivo .jwt_secret tinha %d bytes (< %d). Regenerando um segredo forte; "
            "sessões existentes serão invalidadas uma vez.",
            len(file_secret.encode()) if file_secret else 0, MIN_BYTES,
        )

    # Gerar novo secret forte e persistir (token_hex(32) -> 64 chars/bytes)
    new_secret = secrets.token_hex(32)
    try:
        _JWT_SECRET_FILE.write_text(new_secret)
    except OSError:
        pass  # Em ambientes read-only, usa o secret em memória
    return new_secret


def _anchor(path_str: str) -> str:
    """Resolve caminhos relativos a partir do diretório do backend (não do cwd).

    Motivo: o servidor pode ser iniciado da raiz do projeto (`uvicorn
    backend.main:app`) ou de dentro de `backend/`. Um DB_PATH relativo como
    `./progress.db` apontaria para arquivos diferentes conforme o cwd — o que
    causava 'no such table' ao subir da raiz (banco vazio). Ancorando no
    diretório do backend, o caminho fica determinístico. Caminhos absolutos
    (produção, testes com tmp) são respeitados sem alteração.
    """
    if not path_str:
        return path_str
    p = Path(path_str)
    if p.is_absolute():
        return str(p)
    return str((_BACKEND_DIR / p).resolve())


class Settings:
    """Configurações da aplicação. Valores podem ser overridden via env vars."""
    PDF_ROOT: str = _anchor(os.environ.get("PDF_ROOT", "./pdfs"))
    DB_PATH: str = _anchor(os.environ.get("DB_PATH", "./progress.db"))
    APP_VERSION: str = "2.4.0"
    BACKUP_DIR: str = _anchor(os.environ.get("BACKUP_DIR", "./backups"))
    BACKUP_MAX_KEEP: int = int(os.environ.get("BACKUP_MAX_KEEP", "7"))
    BACKUP_AUTO: bool = os.environ.get("BACKUP_AUTO", "true").lower() == "true"
    CORS_ORIGINS: list = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://0.0.0.0:8000",
    ]

    # Environment
    ENV: str = os.environ.get("ENV", "dev")

    # JWT
    JWT_SECRET: str = _get_jwt_secret()
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = int(os.environ.get("JWT_EXPIRE_HOURS", "1"))
    JWT_REFRESH_EXPIRE_DAYS: int = int(os.environ.get("JWT_REFRESH_EXPIRE_DAYS", "7"))

    # Email SMTP
    SMTP_HOST: str = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT: int = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER: str = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD: str = os.environ.get("SMTP_PASSWORD", "")
    SMTP_FROM: str = os.environ.get("SMTP_FROM", "")
    SMTP_USE_TLS: bool = os.environ.get("SMTP_USE_TLS", "true").lower() == "true"

    # Auth
    AUTH_CODE_EXPIRE_MINUTES: int = int(os.environ.get("AUTH_CODE_EXPIRE_MINUTES", "10"))
    AUTH_ENABLED: bool = os.environ.get("AUTH_ENABLED", "false").lower() == "true"

    # Plano padrão para modo local (sem login): "guest", "free", "premium", "ilimitado"
    DEFAULT_PLAN: str = os.environ.get("DEFAULT_PLAN", "premium")

    # AI Tutor — Multi-Provider Support
    # Provider priority: uses first configured provider found
    # Supported: openai, claude, gemini, grok, deepseek, mistral, groq, together, cohere, perplexity, kimi, glm, bedrock, ollama
    OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")  # Claude
    GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
    XAI_API_KEY: str = os.environ.get("XAI_API_KEY", "")        # Grok
    DEEPSEEK_API_KEY: str = os.environ.get("DEEPSEEK_API_KEY", "")
    MISTRAL_API_KEY: str = os.environ.get("MISTRAL_API_KEY", "")
    GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")      # Fast inference
    TOGETHER_API_KEY: str = os.environ.get("TOGETHER_API_KEY", "")
    COHERE_API_KEY: str = os.environ.get("COHERE_API_KEY", "")
    PERPLEXITY_API_KEY: str = os.environ.get("PERPLEXITY_API_KEY", "")
    KIMI_API_KEY: str = os.environ.get("KIMI_API_KEY", "")      # Moonshot AI
    GLM_API_KEY: str = os.environ.get("GLM_API_KEY", "")        # ZhipuAI (ChatGLM)
    AWS_BEDROCK_REGION: str = os.environ.get("AWS_BEDROCK_REGION", "")
    AWS_BEDROCK_MODEL: str = os.environ.get("AWS_BEDROCK_MODEL", "anthropic.claude-3-haiku-20240307-v1:0")
    OLLAMA_URL: str = os.environ.get("OLLAMA_URL", "http://localhost:11434")
    AI_MODEL: str = os.environ.get("AI_MODEL", "")  # Override model for any provider
    AI_PROVIDER: str = os.environ.get("AI_PROVIDER", "auto")  # auto | openai | claude | gemini | grok | deepseek | mistral | groq | together | cohere | perplexity | kimi | glm | bedrock | ollama
    AI_DAILY_TOKEN_LIMIT: int = int(os.environ.get("AI_DAILY_TOKEN_LIMIT", "50000"))

    # Rate Limiting (requests per minute)
    RATE_LIMIT_GENERAL: int = int(os.environ.get("RATE_LIMIT_GENERAL", "500"))
    RATE_LIMIT_AUTH: int = int(os.environ.get("RATE_LIMIT_AUTH", "10"))
    RATE_LIMIT_AI: int = int(os.environ.get("RATE_LIMIT_AI", "20"))

    # Monitoring — Sentry (optional)
    SENTRY_DSN: str = os.environ.get("SENTRY_DSN", "")

    # Backup offsite — S3-compatible storage (optional)
    S3_BUCKET: str = os.environ.get("S3_BUCKET", "")
    S3_REGION: str = os.environ.get("S3_REGION", "us-east-1")
    S3_PREFIX: str = os.environ.get("S3_PREFIX", "backups")

    # Push Notifications (VAPID)
    VAPID_PRIVATE_KEY: str = os.environ.get("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY: str = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_SUBJECT: str = os.environ.get("VAPID_SUBJECT", "mailto:admin@concurseiroos.app")

    # Pagamentos (Mercado Pago)
    MERCADO_PAGO_ACCESS_TOKEN: str = os.environ.get("MERCADO_PAGO_ACCESS_TOKEN", "")
    MERCADO_PAGO_WEBHOOK_SECRET: str = os.environ.get("MERCADO_PAGO_WEBHOOK_SECRET", "")
    PIX_CHAVE: str = os.environ.get("PIX_CHAVE", "99981368527")

    # Janela de venda do plano Vitalício (ISO format: YYYY-MM-DD)
    # Fora do período entre INICIO e FIM, o plano Vitalício não pode ser adquirido.
    # Deixar vazio = sempre disponível (para testes/dev).
    VITALICIO_VENDA_INICIO: str = os.environ.get("VITALICIO_VENDA_INICIO", "")  # ex: "2026-09-01"
    VITALICIO_VENDA_FIM: str = os.environ.get("VITALICIO_VENDA_FIM", "")        # ex: "2026-09-07"


settings = Settings()

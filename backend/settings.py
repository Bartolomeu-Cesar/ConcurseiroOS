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
    """Obtém JWT_SECRET de forma persistente.

    1. Se env var JWT_SECRET está definida, usa ela
    2. Se arquivo .jwt_secret existe, lê dele
    3. Senão, gera um novo secret e salva no arquivo
    """
    env_secret = os.environ.get("JWT_SECRET")
    if env_secret:
        return env_secret

    if _JWT_SECRET_FILE.exists():
        return _JWT_SECRET_FILE.read_text().strip()

    # Gerar novo secret e persistir
    new_secret = secrets.token_hex(32)
    try:
        _JWT_SECRET_FILE.write_text(new_secret)
    except OSError:
        pass  # Em ambientes read-only, usa o secret em memória
    return new_secret


class Settings:
    """Configurações da aplicação. Valores podem ser overridden via env vars."""
    PDF_ROOT: str = os.environ.get("PDF_ROOT", "./pdfs")
    DB_PATH: str = os.environ.get("DB_PATH", "./progress.db")
    APP_VERSION: str = "2.3.0"
    BACKUP_DIR: str = os.environ.get("BACKUP_DIR", "./backups")
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
    JWT_EXPIRE_HOURS: int = int(os.environ.get("JWT_EXPIRE_HOURS", "72"))

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

    # Push Notifications (VAPID)
    VAPID_PRIVATE_KEY: str = os.environ.get("VAPID_PRIVATE_KEY", "")
    VAPID_PUBLIC_KEY: str = os.environ.get("VAPID_PUBLIC_KEY", "")
    VAPID_SUBJECT: str = os.environ.get("VAPID_SUBJECT", "mailto:admin@concurseiroos.app")


settings = Settings()

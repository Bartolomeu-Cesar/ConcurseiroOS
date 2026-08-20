"""Configurações centralizadas do ConcurseiroOS."""
import os
import secrets
from pathlib import Path

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


settings = Settings()

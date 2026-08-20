"""Configurações centralizadas do ConcurseiroOS."""
import os
import secrets


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

    # JWT
    JWT_SECRET: str = os.environ.get("JWT_SECRET", secrets.token_hex(32))
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

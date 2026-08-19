"""Configurações centralizadas do ConcurseiroOS."""
import os


class Settings:
    """Configurações da aplicação. Valores podem ser overridden via env vars."""
    PDF_ROOT: str = os.environ.get("PDF_ROOT", "./pdfs")
    DB_PATH: str = os.environ.get("DB_PATH", "./progress.db")
    APP_VERSION: str = "2.2.0"
    BACKUP_DIR: str = os.environ.get("BACKUP_DIR", "./backups")
    CORS_ORIGINS: list = [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://0.0.0.0:8000",
    ]


settings = Settings()

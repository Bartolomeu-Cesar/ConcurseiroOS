"""Sistema de backup automático do ConcurseiroOS.

Features:
- create_backup() — copia progress.db para backups/ com timestamp
- rotate_backups(max_keep) — mantém apenas os últimos N backups
- schedule_daily_backup() — agenda backup diário via threading.Timer
- restore_from_backup(filename) — restaura um backup específico
- list_backups() — lista backups disponíveis com tamanho e data
"""
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path

from constants import BACKUP_INTERVAL_HOURS, MAX_BACKUPS
from settings import settings

BACKUP_DIR = Path(settings.BACKUP_DIR)

# Timer reference for scheduled backup
_backup_timer: threading.Timer | None = None


def ensure_backup_dir():
    """Garante que o diretório de backup existe."""
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def create_backup(db_path: str | None = None) -> str:
    """Cria backup do banco de dados com timestamp.

    Filename format: backup_2026-08-21_210000.db
    """
    if db_path is None:
        db_path = settings.DB_PATH

    ensure_backup_dir()

    # Check if source DB exists
    if not Path(db_path).exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup_name = f"backup_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(db_path, backup_path)
    rotate_backups()
    return str(backup_path)


def rotate_backups(max_keep: int | None = None):
    """Mantém apenas os últimos max_keep backups, apaga os mais antigos.

    Args:
        max_keep: Número máximo de backups a manter.
                  Default: settings.BACKUP_MAX_KEEP ou MAX_BACKUPS.
    """
    if max_keep is None:
        max_keep = getattr(settings, "BACKUP_MAX_KEEP", MAX_BACKUPS)

    ensure_backup_dir()
    backups = sorted(BACKUP_DIR.glob("backup_*.db"), key=os.path.getmtime)
    # Also include legacy format for cleanup
    legacy = sorted(BACKUP_DIR.glob("progress_backup_*.db"), key=os.path.getmtime)
    all_backups = sorted(backups + legacy, key=os.path.getmtime)

    while len(all_backups) > max_keep:
        all_backups[0].unlink()
        all_backups.pop(0)


def list_backups() -> list[dict]:
    """Lista backups disponíveis com nome, tamanho e data.

    Returns:
        Lista de dicts com filename, size_mb e created.
    """
    ensure_backup_dir()
    # Match both new and legacy formats
    new_backups = list(BACKUP_DIR.glob("backup_*.db"))
    legacy_backups = list(BACKUP_DIR.glob("progress_backup_*.db"))
    all_backups = sorted(new_backups + legacy_backups, key=os.path.getmtime, reverse=True)

    return [{
        "filename": b.name,
        "size_mb": round(b.stat().st_size / 1024 / 1024, 2),
        "created": datetime.fromtimestamp(b.stat().st_mtime).isoformat()
    } for b in all_backups]


def restore_from_backup(filename: str, db_path: str | None = None) -> bool:
    """Restaura um backup específico.

    Cria um backup do estado atual antes de restaurar.

    Args:
        filename: Nome do arquivo de backup (sem path).
        db_path: Caminho do banco de dados a restaurar.

    Returns:
        True se restaurou com sucesso, False caso contrário.
    """
    if db_path is None:
        db_path = settings.DB_PATH

    # Path traversal protection
    if ".." in filename or "/" in filename or "\\" in filename:
        return False

    backup_path = (BACKUP_DIR / filename).resolve()
    # Validate resolved path is within BACKUP_DIR
    if not backup_path.is_relative_to(BACKUP_DIR.resolve()):
        return False

    if not backup_path.exists():
        return False

    # Backup do estado atual antes de restaurar
    try:
        create_backup(db_path)
    except FileNotFoundError:
        pass  # DB might not exist yet

    shutil.copy2(backup_path, db_path)
    return True


# Keep backward-compatible alias
restore_backup = restore_from_backup


def delete_backup(filename: str) -> bool:
    """Remove um backup específico.

    Args:
        filename: Nome do arquivo de backup (sem path).

    Returns:
        True se removeu, False se não encontrou ou path inválido.
    """
    # Path traversal protection
    if ".." in filename or "/" in filename or "\\" in filename:
        return False

    backup_path = (BACKUP_DIR / filename).resolve()
    if not backup_path.is_relative_to(BACKUP_DIR.resolve()):
        return False

    if not backup_path.exists():
        return False

    backup_path.unlink()
    return True


def schedule_daily_backup(db_path: str | None = None):
    """Agenda backup automático a cada 24h usando threading.Timer.

    O timer roda em daemon mode para não impedir o shutdown do processo.
    """
    global _backup_timer

    if db_path is None:
        db_path = settings.DB_PATH

    if not getattr(settings, "BACKUP_AUTO", True):
        return

    def _run_backup():
        try:
            create_backup(db_path)
            from logger import log
            log.info("Auto backup criado com sucesso")
        except Exception as e:
            from logger import log
            log.error(f"Erro no auto backup: {e}")
        finally:
            # Re-agendar para próximo intervalo
            schedule_daily_backup(db_path)

    interval_seconds = BACKUP_INTERVAL_HOURS * 3600
    _backup_timer = threading.Timer(interval_seconds, _run_backup)
    _backup_timer.daemon = True
    _backup_timer.start()


def auto_backup_if_needed(db_path: str | None = None):
    """Cria backup se o último foi há mais de BACKUP_INTERVAL_HOURS.

    Chamado na inicialização do app para garantir backup recente.
    """
    if db_path is None:
        db_path = settings.DB_PATH

    ensure_backup_dir()

    # Check both formats
    new_backups = list(BACKUP_DIR.glob("backup_*.db"))
    legacy_backups = list(BACKUP_DIR.glob("progress_backup_*.db"))
    all_backups = sorted(new_backups + legacy_backups, key=os.path.getmtime, reverse=True)

    if not all_backups:
        try:
            create_backup(db_path)
        except FileNotFoundError:
            pass
        return

    last_backup_time = datetime.fromtimestamp(all_backups[0].stat().st_mtime)
    if (datetime.now() - last_backup_time).total_seconds() > BACKUP_INTERVAL_HOURS * 3600:
        try:
            create_backup(db_path)
        except FileNotFoundError:
            pass

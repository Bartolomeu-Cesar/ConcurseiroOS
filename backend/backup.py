import shutil
import os
from datetime import datetime, date
from pathlib import Path

BACKUP_DIR = Path("./backups")
MAX_BACKUPS = 7


def ensure_backup_dir():
    BACKUP_DIR.mkdir(exist_ok=True)


def create_backup(db_path: str) -> str:
    """Cria backup do banco de dados com timestamp."""
    ensure_backup_dir()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"progress_backup_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name
    shutil.copy2(db_path, backup_path)
    rotate_backups()
    return str(backup_path)


def rotate_backups():
    """Mantém apenas os últimos MAX_BACKUPS arquivos."""
    ensure_backup_dir()
    backups = sorted(BACKUP_DIR.glob("progress_backup_*.db"), key=os.path.getmtime)
    while len(backups) > MAX_BACKUPS:
        backups[0].unlink()
        backups.pop(0)


def list_backups() -> list:
    """Lista backups disponíveis."""
    ensure_backup_dir()
    backups = sorted(BACKUP_DIR.glob("progress_backup_*.db"), key=os.path.getmtime, reverse=True)
    return [{
        "filename": b.name,
        "size_mb": round(b.stat().st_size / 1024 / 1024, 2),
        "created": datetime.fromtimestamp(b.stat().st_mtime).isoformat()
    } for b in backups]


def restore_backup(filename: str, db_path: str) -> bool:
    """Restaura um backup específico."""
    backup_path = BACKUP_DIR / filename
    if not backup_path.exists():
        return False
    # Backup do atual antes de restaurar
    create_backup(db_path)
    shutil.copy2(backup_path, db_path)
    return True


def auto_backup_if_needed(db_path: str):
    """Cria backup se o último foi há mais de 24h."""
    ensure_backup_dir()
    backups = sorted(BACKUP_DIR.glob("progress_backup_*.db"), key=os.path.getmtime, reverse=True)
    if not backups:
        create_backup(db_path)
        return
    last_backup_time = datetime.fromtimestamp(backups[0].stat().st_mtime)
    if (datetime.now() - last_backup_time).total_seconds() > 86400:  # 24h
        create_backup(db_path)

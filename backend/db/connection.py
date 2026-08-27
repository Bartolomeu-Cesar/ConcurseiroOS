"""Conexão com o banco de dados SQLite e configuração de PRAGMAs."""
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from logger import log
from settings import settings

DB_PATH = settings.DB_PATH

_PRAGMAS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=5000",
    "PRAGMA cache_size=-8000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=268435456",
    "PRAGMA foreign_keys=ON",
]


def _apply_pragmas(conn):
    """Aplica PRAGMAs de performance na conexão."""
    for pragma in _PRAGMAS:
        conn.execute(pragma)


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    try:
        yield conn
    finally:
        conn.close()


def get_db_session() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency que fornece uma conexão ao banco de dados."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    try:
        yield conn
    finally:
        conn.close()

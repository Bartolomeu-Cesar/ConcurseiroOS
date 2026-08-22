"""Orquestrador de inicialização do banco de dados."""
import sqlite3

from logger import log

from . import connection as _connection
from .indexes import _create_indexes
from .migrations import _run_migrations
from .search import _create_fts5_triggers, rebuild_search_index
from .seeds import _seed_defaults
from .tables import _create_tables


def init_db():
    """Inicializa o banco de dados: tabelas, migrações, índices e dados padrão."""
    conn = sqlite3.connect(_connection.DB_PATH)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode for better concurrent read performance
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    _create_tables(conn)
    _run_migrations(conn)
    _create_indexes(conn)
    _seed_defaults(conn)
    conn.commit()
    rebuild_search_index(conn)
    _create_fts5_triggers(conn)
    conn.close()
    log.info("Database initialized (WAL mode)")

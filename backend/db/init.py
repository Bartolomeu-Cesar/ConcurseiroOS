"""Orquestrador de inicialização do banco de dados."""
import os
import sqlite3
import time

from logger import log

from . import connection as _connection
from .indexes import _create_indexes
from .migrations import _run_migrations
from .search import _create_fts5_triggers, rebuild_search_index
from .seeds import _seed_defaults
from .tables import _create_tables

_VACUUM_INTERVAL = 86400  # 24 horas em segundos
_VACUUM_MARKER = os.path.join(os.path.dirname(_connection.DB_PATH), ".last_vacuum")


def _maybe_vacuum(conn):
    """Roda VACUUM + ANALYZE se passou mais de 24h desde o último."""
    try:
        if os.path.exists(_VACUUM_MARKER):
            last = os.path.getmtime(_VACUUM_MARKER)
            if (time.time() - last) < _VACUUM_INTERVAL:
                return  # Ainda não é hora

        # ANALYZE atualiza estatísticas do query planner
        conn.execute("ANALYZE")
        conn.commit()
        # VACUUM precisa ser fora de transação
        conn.execute("VACUUM")
        # Atualiza marker
        with open(_VACUUM_MARKER, "w") as f:
            f.write(str(int(time.time())))
        log.info("Database maintenance: VACUUM + ANALYZE completed")
    except Exception as e:
        log.warning(f"Database maintenance skipped: {e}")


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
    _maybe_vacuum(conn)
    conn.close()
    log.info("Database initialized (WAL mode)")

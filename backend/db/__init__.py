"""Pacote db — módulo de banco de dados dividido em sub-módulos.

Re-exporta todos os símbolos públicos para manter compatibilidade.
"""
from .connection import DB_PATH, get_db, get_db_session
from .init import init_db
from .search import rebuild_search_index

__all__ = [
    "DB_PATH",
    "get_db",
    "get_db_session",
    "init_db",
    "rebuild_search_index",
]

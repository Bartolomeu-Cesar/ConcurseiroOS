"""Módulo de banco de dados — thin wrapper para backward compatibility.

Toda a implementação está no pacote `db/`. Este arquivo mantém a API pública
para que `from database import get_db, init_db, ...` continue funcionando.

Suporta mutação de DB_PATH (ex: testes que fazem database.DB_PATH = '...').
"""
import os
import sys

# PostgreSQL support: if DATABASE_URL is set, delegate to database_pg module
_DATABASE_URL = os.environ.get("DATABASE_URL", "")
_USE_PG = _DATABASE_URL.startswith("postgresql://") or _DATABASE_URL.startswith("postgres://")

if _USE_PG:
    from database_pg import get_db, get_db_session, init_db  # noqa: F811, F401
    from database_pg import rebuild_search_index, DB_PATH  # noqa: F811, F401
else:
    from db import get_db, get_db_session, init_db, rebuild_search_index  # noqa: F401
    import db.connection as _connection

    DB_PATH = _connection.DB_PATH


def __getattr__(name):
    """Fallback para leitura de DB_PATH atualizado."""
    if name == "DB_PATH" and not _USE_PG:
        return _connection.DB_PATH
    raise AttributeError(f"module 'database' has no attribute {name!r}")


# Intercept attribute assignment so that `database.DB_PATH = x` propagates
# to the actual connection module where get_db/init_db read it from.
_this_module = sys.modules[__name__]
_original_class = type(_this_module)


class _ModuleWithSetattr(_original_class):
    def __setattr__(self, name, value):
        if name == "DB_PATH" and not _USE_PG:
            _connection.DB_PATH = value
        super().__setattr__(name, value)


_this_module.__class__ = _ModuleWithSetattr

__all__ = [
    "DB_PATH",
    "get_db",
    "get_db_session",
    "init_db",
    "rebuild_search_index",
]

"""
database_pg.py - PostgreSQL backend for ConcurseiroOS (multi-user production).

Drop-in replacement for database.py when DATABASE_URL is set.
Uses psycopg2 with ThreadedConnectionPool for concurrent access.
"""
import os
import re
from collections.abc import Generator
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

from logger import log

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PATH = DATABASE_URL  # Alias for compatibility (used by some modules to check if DB is configured)

_MIN_CONNECTIONS = int(os.environ.get("PG_POOL_MIN", "2"))
_MAX_CONNECTIONS = int(os.environ.get("PG_POOL_MAX", "20"))

# ---------------------------------------------------------------------------
# Connection Pool (lazy-initialized)
# ---------------------------------------------------------------------------
_pool: ThreadedConnectionPool | None = None


def _get_pool() -> ThreadedConnectionPool:
    """Return the global connection pool, creating it if needed."""
    global _pool
    if _pool is None or _pool.closed:
        _pool = ThreadedConnectionPool(
            _MIN_CONNECTIONS,
            _MAX_CONNECTIONS,
            DATABASE_URL,
        )
        log.info(f"PostgreSQL pool created (min={_MIN_CONNECTIONS}, max={_MAX_CONNECTIONS})")
    return _pool


# ---------------------------------------------------------------------------
# Public interface (same as database.py)
# ---------------------------------------------------------------------------

class DictRow:
    """Wrapper to make psycopg2 DictRow behave like sqlite3.Row (subscriptable by index and name)."""

    def __init__(self, row):
        self._row = row

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self._row.values())[key]
        return self._row[key]

    def keys(self):
        return self._row.keys()

    def __iter__(self):
        return iter(self._row.values())

    def __len__(self):
        return len(self._row)


class PgConnectionWrapper:
    """
    Wraps a psycopg2 connection to provide an interface compatible with the
    sqlite3.Connection usage in the rest of the app (conn.execute(...), conn.commit(), etc).
    Results are returned as DictRow objects for sqlite3.Row compatibility.
    """

    def __init__(self, conn):
        self._conn = conn
        self._conn.autocommit = False

    def execute(self, sql: str, params=None):
        """Execute a query, translating SQLite idioms to PostgreSQL."""
        sql = _translate_sql(sql)
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute(sql, params or None)
        except Exception:
            self._conn.rollback()
            raise
        return PgCursorWrapper(cur)

    def executemany(self, sql: str, params_list):
        sql = _translate_sql(sql)
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            for params in params_list:
                cur.execute(sql, params)
        except Exception:
            self._conn.rollback()
            raise
        return PgCursorWrapper(cur)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        # Return connection to pool instead of closing
        try:
            self._conn.rollback()  # Discard uncommitted changes
        except Exception:
            pass
        try:
            _get_pool().putconn(self._conn)
        except Exception:
            pass

    @property
    def raw(self):
        """Access the underlying psycopg2 connection."""
        return self._conn


class PgCursorWrapper:
    """Wraps psycopg2 cursor to return DictRow objects."""

    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return DictRow(row)

    def fetchall(self):
        rows = self._cursor.fetchall()
        return [DictRow(r) for r in rows]

    @property
    def lastrowid(self):
        return self._cursor.fetchone()["id"] if self._cursor.description else None

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def __iter__(self):
        return iter(self.fetchall())


# ---------------------------------------------------------------------------
# SQL Translation (SQLite → PostgreSQL)
# ---------------------------------------------------------------------------

def _translate_sql(sql: str) -> str:
    """Translate common SQLite-specific SQL to PostgreSQL equivalents."""
    if not sql or not sql.strip():
        return sql

    original = sql

    # Skip PRAGMA statements entirely (return a no-op SELECT)
    if sql.strip().upper().startswith("PRAGMA"):
        return "SELECT 1"

    # Skip FTS5 virtual tables (not supported in PG - use pg_trgm/tsvector instead)
    if "USING fts5" in sql.upper() or "USING FTS5" in sql:
        return "SELECT 1"

    # Skip SQLite triggers that reference FTS tables (search_index)
    if "CREATE TRIGGER" in sql.upper() and "search_index" in sql:
        return "SELECT 1"

    # AUTOINCREMENT → use SERIAL (handled in CREATE TABLE)
    # Replace "INTEGER PRIMARY KEY AUTOINCREMENT" with "SERIAL PRIMARY KEY"
    sql = re.sub(
        r'(\w+)\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT',
        r'\1 SERIAL PRIMARY KEY',
        sql,
        flags=re.IGNORECASE
    )

    # "INTEGER PRIMARY KEY DEFAULT 1" → "INTEGER PRIMARY KEY DEFAULT 1" (keep as is)

    # REAL → DOUBLE PRECISION (in column definitions)
    sql = re.sub(
        r'\bREAL\b(?!\s*\()',
        'DOUBLE PRECISION',
        sql,
        flags=re.IGNORECASE
    )

    # datetime('now') → NOW()
    sql = re.sub(
        r"datetime\s*\(\s*'now'\s*\)",
        "NOW()",
        sql,
        flags=re.IGNORECASE
    )

    # INSERT OR IGNORE → INSERT ... ON CONFLICT DO NOTHING
    sql = re.sub(
        r'INSERT\s+OR\s+IGNORE\s+INTO',
        'INSERT INTO',
        sql,
        flags=re.IGNORECASE
    )
    if "ON CONFLICT" not in sql.upper() and original.upper().startswith("INSERT OR IGNORE"):
        # Append ON CONFLICT DO NOTHING at the end
        sql = sql.rstrip().rstrip(';') + " ON CONFLICT DO NOTHING"

    # GROUP_CONCAT(x) → STRING_AGG(x::TEXT, ',')
    sql = re.sub(
        r"GROUP_CONCAT\s*\(\s*([^)]+)\s*\)",
        r"STRING_AGG(\1::TEXT, ',')",
        sql,
        flags=re.IGNORECASE
    )

    # GROUP_CONCAT(x, sep) → STRING_AGG(x::TEXT, sep)
    # (already handled by the above pattern since the separator is in the arg)

    # SQLite ? placeholders → %s for psycopg2
    sql = sql.replace("?", "%s")

    # CAST(x AS TEXT) is fine in PG, no change needed

    # TEXT type is valid in PG, keep as is

    # "IF NOT EXISTS" for CREATE INDEX is valid in PG 9.5+

    # Boolean: SQLite uses 0/1, PG supports both (INTEGER columns store 0/1 fine)

    return sql


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------

@contextmanager
def get_db():
    """Context manager providing a PostgreSQL connection (pool-backed)."""
    pool = _get_pool()
    raw_conn = pool.getconn()
    wrapper = PgConnectionWrapper(raw_conn)
    try:
        yield wrapper
    finally:
        wrapper.close()


def get_db_session() -> Generator:
    """FastAPI dependency that provides a PostgreSQL connection."""
    pool = _get_pool()
    raw_conn = pool.getconn()
    wrapper = PgConnectionWrapper(raw_conn)
    try:
        yield wrapper
    finally:
        wrapper.close()


# ---------------------------------------------------------------------------
# Full-text search (PostgreSQL tsvector-based alternative to FTS5)
# ---------------------------------------------------------------------------

def _create_search_table(conn):
    """Create a search_index table using PostgreSQL tsvector for full-text search."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS search_index (
            id SERIAL PRIMARY KEY,
            source TEXT NOT NULL,
            source_id TEXT NOT NULL,
            title TEXT DEFAULT '',
            content TEXT DEFAULT '',
            tsv tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('portuguese', coalesce(title, '')), 'A') ||
                setweight(to_tsvector('portuguese', coalesce(content, '')), 'B')
            ) STORED
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_search_index_tsv ON search_index USING GIN(tsv)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_search_index_source ON search_index(source, source_id)
    """)


# ---------------------------------------------------------------------------
# Table creation (PostgreSQL version)
# ---------------------------------------------------------------------------

def _create_tables(conn):
    """Create all system tables (PostgreSQL-compatible DDL)."""

    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            path TEXT PRIMARY KEY,
            current_page INTEGER DEFAULT 1,
            total_pages INTEGER DEFAULT 1,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS edital (
            id SERIAL PRIMARY KEY,
            edital_nome TEXT DEFAULT 'Geral',
            cargo TEXT DEFAULT '',
            materia TEXT NOT NULL,
            topico TEXT NOT NULL,
            status TEXT DEFAULT 'Não Iniciado',
            horas_estudadas DOUBLE PRECISION DEFAULT 0.0,
            pdf_link TEXT DEFAULT '',
            pdf_pagina INTEGER DEFAULT 0,
            arquivado INTEGER DEFAULT 0,
            proxima_revisao TEXT DEFAULT '',
            intervalo_revisao INTEGER DEFAULT 1,
            easiness_factor_edital DOUBLE PRECISION DEFAULT 2.5,
            repetitions_edital INTEGER DEFAULT 0,
            stability_edital DOUBLE PRECISION DEFAULT 0,
            difficulty_edital DOUBLE PRECISION DEFAULT 0,
            fsrs_state_edital INTEGER DEFAULT 0,
            mastery_level DOUBLE PRECISION DEFAULT 0,
            mastery_updated_at TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS flashcards (
            id SERIAL PRIMARY KEY,
            pergunta TEXT NOT NULL,
            resposta TEXT NOT NULL,
            proxima_revisao TEXT NOT NULL,
            intervalo_dias INTEGER DEFAULT 1,
            easiness_factor DOUBLE PRECISION DEFAULT 2.5,
            repetitions INTEGER DEFAULT 0,
            materia TEXT DEFAULT '',
            stability DOUBLE PRECISION DEFAULT 0,
            difficulty DOUBLE PRECISION DEFAULT 0,
            fsrs_state INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS questoes (
            id SERIAL PRIMARY KEY,
            materia TEXT NOT NULL,
            topico TEXT DEFAULT '',
            enunciado TEXT NOT NULL,
            alternativa_a TEXT NOT NULL,
            alternativa_b TEXT NOT NULL,
            alternativa_c TEXT NOT NULL,
            alternativa_d TEXT NOT NULL,
            alternativa_e TEXT DEFAULT '',
            resposta_correta TEXT NOT NULL,
            explicacao TEXT DEFAULT '',
            dificuldade TEXT DEFAULT 'Médio',
            created_at TEXT NOT NULL,
            banca TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS questoes_respostas (
            id SERIAL PRIMARY KEY,
            questao_id INTEGER NOT NULL REFERENCES questoes(id),
            resposta_usuario TEXT NOT NULL,
            acertou INTEGER NOT NULL,
            tempo_segundos INTEGER DEFAULT 0,
            data TEXT NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulados (
            id SERIAL PRIMARY KEY,
            titulo TEXT NOT NULL,
            tempo_limite_min INTEGER DEFAULT 60,
            status TEXT DEFAULT 'pendente',
            nota DOUBLE PRECISION DEFAULT 0.0,
            total_questoes INTEGER DEFAULT 0,
            acertos INTEGER DEFAULT 0,
            tempo_gasto_seg INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            finalizado_at TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulado_questoes (
            id SERIAL PRIMARY KEY,
            simulado_id INTEGER NOT NULL REFERENCES simulados(id),
            questao_id INTEGER NOT NULL REFERENCES questoes(id),
            ordem INTEGER DEFAULT 0,
            resposta_usuario TEXT DEFAULT '',
            acertou INTEGER DEFAULT -1,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ciclo_estudos (
            id SERIAL PRIMARY KEY,
            materia TEXT NOT NULL,
            horas_alvo DOUBLE PRECISION DEFAULT 1.0,
            horas_cumpridas DOUBLE PRECISION DEFAULT 0.0,
            ordem INTEGER DEFAULT 0,
            ativo INTEGER DEFAULT 1,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessoes_estudo (
            id SERIAL PRIMARY KEY,
            materia TEXT NOT NULL,
            horas DOUBLE PRECISION NOT NULL,
            data TEXT NOT NULL,
            tipo TEXT DEFAULT 'edital',
            created_at TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            id SERIAL PRIMARY KEY,
            data TEXT UNIQUE NOT NULL,
            horas_estudadas DOUBLE PRECISION DEFAULT 0.0,
            questoes_resolvidas INTEGER DEFAULT 0,
            flashcards_revisados INTEGER DEFAULT 0,
            sumulas_revisadas INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS metas_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            meta_horas DOUBLE PRECISION DEFAULT 3.0,
            meta_questoes INTEGER DEFAULT 30,
            meta_flashcards INTEGER DEFAULT 10,
            meta_paginas INTEGER DEFAULT 20,
            meta_sumulas INTEGER DEFAULT 0,
            streak_freezes_available INTEGER DEFAULT 1,
            streak_freezes_used INTEGER DEFAULT 0,
            last_freeze_earned TEXT DEFAULT '',
            desired_retention DOUBLE PRECISION DEFAULT 0.9,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notas_pdf (
            id SERIAL PRIMARY KEY,
            pdf_path TEXT NOT NULL,
            pagina INTEGER DEFAULT 1,
            conteudo TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS edital_info (
            id SERIAL PRIMARY KEY,
            edital_nome TEXT NOT NULL,
            cargo TEXT DEFAULT '',
            orgao TEXT DEFAULT '',
            banca TEXT DEFAULT '',
            vagas TEXT DEFAULT '',
            subsidio TEXT DEFAULT '',
            inscricoes TEXT DEFAULT '',
            data_prova_objetiva TEXT DEFAULT '',
            data_prova_discursiva TEXT DEFAULT '',
            horario TEXT DEFAULT '',
            local_prova TEXT DEFAULT '',
            taxa_inscricao TEXT DEFAULT '',
            link_edital TEXT DEFAULT '',
            observacoes TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS planejador_semanal (
            id SERIAL PRIMARY KEY,
            dia_semana INTEGER NOT NULL,
            materia TEXT NOT NULL,
            horas DOUBLE PRECISION DEFAULT 1.0,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notas_topico (
            id SERIAL PRIMARY KEY,
            edital_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cadernos (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS caderno_itens (
            id SERIAL PRIMARY KEY,
            caderno_id INTEGER NOT NULL REFERENCES cadernos(id),
            tipo TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks_pdf (
            id SERIAL PRIMARY KEY,
            pdf_path TEXT NOT NULL,
            pagina INTEGER NOT NULL,
            label TEXT DEFAULT '',
            cor TEXT DEFAULT 'blue',
            created_at TEXT NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS feynman (
            id SERIAL PRIMARY KEY,
            edital_id INTEGER NOT NULL,
            explicacao TEXT NOT NULL,
            created_at TEXT NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS desafios (
            id SERIAL PRIMARY KEY,
            titulo TEXT NOT NULL,
            meta_tipo TEXT NOT NULL,
            meta_valor INTEGER NOT NULL,
            materia TEXT DEFAULT '',
            progresso INTEGER DEFAULT 0,
            dias INTEGER DEFAULT 7,
            created_at TEXT NOT NULL,
            finalizado INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS resumos (
            id SERIAL PRIMARY KEY,
            edital_id INTEGER NOT NULL,
            resumo TEXT NOT NULL,
            tipo TEXT DEFAULT 'livre',
            created_at TEXT NOT NULL,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_personalizado (
            id SERIAL PRIMARY KEY,
            dia_semana INTEGER NOT NULL,
            materia TEXT NOT NULL,
            topicos TEXT DEFAULT '',
            tempo_min INTEGER DEFAULT 60,
            tipo TEXT DEFAULT 'estudo',
            ordem INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_atividades (
            id SERIAL PRIMARY KEY,
            data TEXT NOT NULL,
            dia_semana INTEGER NOT NULL,
            materia TEXT DEFAULT '',
            tipo TEXT DEFAULT 'estudo',
            tempo_min INTEGER DEFAULT 0,
            concluida INTEGER DEFAULT 0,
            concluida_at TEXT DEFAULT '',
            user_id INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_streaks (
            data TEXT PRIMARY KEY,
            total_atividades INTEGER DEFAULT 0,
            concluidas INTEGER DEFAULT 0,
            pct_conclusao DOUBLE PRECISION DEFAULT 0.0,
            xp_bonus INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 1
        )
    """)

    # ========== LEAGUES ==========
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leagues (
            id SERIAL PRIMARY KEY,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'bronze',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS league_members (
            id SERIAL PRIMARY KEY,
            league_id INTEGER NOT NULL REFERENCES leagues(id),
            user_id INTEGER NOT NULL,
            weekly_xp INTEGER DEFAULT 0,
            rank INTEGER DEFAULT 0,
            promoted INTEGER DEFAULT 0,
            demoted INTEGER DEFAULT 0,
            is_bot INTEGER DEFAULT 0,
            bot_name TEXT DEFAULT '',
            joined_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS league_history (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            tier TEXT NOT NULL,
            final_rank INTEGER NOT NULL DEFAULT 0,
            final_xp INTEGER DEFAULT 0,
            promoted INTEGER DEFAULT 0,
            demoted INTEGER DEFAULT 0,
            created_at TEXT DEFAULT ''
        )
    """)

    # ========== AI TUTOR ==========
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_usage (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            data TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            requests_count INTEGER DEFAULT 0,
            UNIQUE(user_id, data)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL DEFAULT 1,
            tipo TEXT NOT NULL DEFAULT 'chat',
            pergunta TEXT NOT NULL,
            resposta TEXT NOT NULL,
            tokens INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)

    # ========== SOCIAL ==========
    conn.execute("""
        CREATE TABLE IF NOT EXISTS friendships (
            id SERIAL PRIMARY KEY,
            user_a INTEGER NOT NULL,
            user_b INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_groups (
            id SERIAL PRIMARY KEY,
            nome TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            edital_nome TEXT DEFAULT '',
            criador_id INTEGER NOT NULL,
            max_membros INTEGER DEFAULT 30,
            publico INTEGER DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            id SERIAL PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES study_groups(id),
            user_id INTEGER NOT NULL,
            role TEXT DEFAULT 'membro',
            joined_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_challenges (
            id SERIAL PRIMARY KEY,
            group_id INTEGER NOT NULL REFERENCES study_groups(id),
            titulo TEXT NOT NULL,
            meta_tipo TEXT NOT NULL,
            meta_valor INTEGER NOT NULL,
            dias INTEGER DEFAULT 7,
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_feed (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            dados TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_gamification (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE,
            xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_badges (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            badge_name TEXT NOT NULL,
            earned_at TEXT NOT NULL
        )
    """)

    # Usuários
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            nome TEXT DEFAULT '',
            username TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
            email_verified INTEGER DEFAULT 0,
            plano TEXT DEFAULT 'free',
            plano_expira TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            last_login TEXT DEFAULT ''
        )
    """)

    # Auth codes
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_codes (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            tipo TEXT DEFAULT 'login',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_attempts (
            id SERIAL PRIMARY KEY,
            email TEXT NOT NULL,
            ip TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    # Súmulas
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sumulas (
            id SERIAL PRIMARY KEY,
            tribunal TEXT NOT NULL,
            numero INTEGER NOT NULL,
            enunciado TEXT NOT NULL,
            tema TEXT DEFAULT '',
            observacao TEXT DEFAULT '',
            vinculante INTEGER DEFAULT 0,
            proxima_revisao TEXT NOT NULL,
            intervalo_dias INTEGER DEFAULT 1,
            easiness_factor DOUBLE PRECISION DEFAULT 2.5,
            repetitions INTEGER DEFAULT 0,
            stability DOUBLE PRECISION DEFAULT 0,
            difficulty_sumulas DOUBLE PRECISION DEFAULT 0,
            fsrs_state INTEGER DEFAULT 0,
            user_id INTEGER DEFAULT 1
        )
    """)

    # Push Notifications
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL UNIQUE,
            streak_risk INTEGER DEFAULT 1,
            flashcards_overdue INTEGER DEFAULT 1,
            exam_approaching INTEGER DEFAULT 1,
            challenge_expiring INTEGER DEFAULT 1,
            quiet_hours_start INTEGER DEFAULT 22,
            quiet_hours_end INTEGER DEFAULT 7,
            updated_at TEXT DEFAULT ''
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            title TEXT DEFAULT '',
            body TEXT DEFAULT '',
            sent_at TEXT NOT NULL,
            success INTEGER DEFAULT 1
        )
    """)

    conn.commit()


def _create_indexes(conn):
    """Create indexes for performance."""
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_streaks_data ON streaks(data)",
        "CREATE INDEX IF NOT EXISTS idx_sessoes_data ON sessoes_estudo(data)",
        "CREATE INDEX IF NOT EXISTS idx_questoes_respostas_data ON questoes_respostas(data)",
        "CREATE INDEX IF NOT EXISTS idx_questoes_materia ON questoes(materia)",
        "CREATE INDEX IF NOT EXISTS idx_edital_nome_cargo ON edital(edital_nome, cargo)",
        "CREATE INDEX IF NOT EXISTS idx_questoes_respostas_questao_id ON questoes_respostas(questao_id)",
        "CREATE INDEX IF NOT EXISTS idx_notas_pdf_path ON notas_pdf(pdf_path)",
        "CREATE INDEX IF NOT EXISTS idx_bookmarks_pdf_path ON bookmarks_pdf(pdf_path)",
        "CREATE INDEX IF NOT EXISTS idx_edital_materia ON edital(materia)",
        "CREATE INDEX IF NOT EXISTS idx_sessoes_data_materia ON sessoes_estudo(data, materia)",
        "CREATE INDEX IF NOT EXISTS idx_questoes_respostas_data_acertou ON questoes_respostas(data, acertou)",
        "CREATE INDEX IF NOT EXISTS idx_edital_status ON edital(status)",
        "CREATE INDEX IF NOT EXISTS idx_edital_nome_cargo_status ON edital(edital_nome, cargo, status)",
        "CREATE INDEX IF NOT EXISTS idx_flashcards_proxima_revisao ON flashcards(proxima_revisao)",
        "CREATE INDEX IF NOT EXISTS idx_sumulas_proxima_revisao ON sumulas(proxima_revisao)",
        "CREATE INDEX IF NOT EXISTS idx_sumulas_tribunal ON sumulas(tribunal)",
        "CREATE INDEX IF NOT EXISTS idx_ciclo_ativo ON ciclo_estudos(ativo)",
        "CREATE INDEX IF NOT EXISTS idx_questoes_respostas_questao_acertou ON questoes_respostas(questao_id, acertou)",
        # User isolation indexes
        "CREATE INDEX IF NOT EXISTS idx_edital_user_id ON edital(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_flashcards_user_id ON flashcards(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_questoes_user_id ON questoes(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_questoes_respostas_user_id ON questoes_respostas(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sessoes_estudo_user_id ON sessoes_estudo(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_streaks_user_id ON streaks(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_simulados_user_id ON simulados(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_ciclo_estudos_user_id ON ciclo_estudos(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_sumulas_user_id ON sumulas(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_metas_config_user_id ON metas_config(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_progress_user_id ON progress(user_id)",
        # Push notifications
        "CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user_id ON push_subscriptions(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_push_subscriptions_endpoint ON push_subscriptions(endpoint)",
        "CREATE INDEX IF NOT EXISTS idx_notification_preferences_user_id ON notification_preferences(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notification_log_user_id ON notification_log(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notification_log_sent_at ON notification_log(sent_at)",
    ]

    for idx_sql in indexes:
        try:
            conn.execute(idx_sql)
        except Exception as e:
            log.warning(f"Index creation skipped: {e}")

    conn.commit()


def _seed_defaults(conn):
    """Insert default data if not present."""
    # Default metas_config for user_id=1
    result = conn.execute("SELECT id FROM metas_config WHERE user_id = %s LIMIT 1", (1,))
    if result.fetchone() is None:
        conn.execute("""
            INSERT INTO metas_config (id, meta_horas, meta_questoes, meta_flashcards, meta_paginas, user_id)
            VALUES (1, 3.0, 30, 10, 20, 1)
            ON CONFLICT (id) DO NOTHING
        """)

    # Default guest user
    result = conn.execute("SELECT id FROM users WHERE id = 1")
    if result.fetchone() is None:
        conn.execute("""
            INSERT INTO users (id, email, nome, username, plano, created_at)
            VALUES (1, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO NOTHING
        """, ('guest@concurseiroos.local', 'Bartholomew Caesar', 'Bartholomew', 'ilimitado'))
        log.info("Seed: created default user (id=1, Bartholomew Caesar)")

    # Seed edital metadados
    result = conn.execute("SELECT COUNT(*) as cnt FROM edital_info")
    row = result.fetchone()
    if row and row["cnt"] == 0:
        import json
        meta_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'editais_metadados.json')
        if os.path.exists(meta_path):
            with open(meta_path, encoding='utf-8') as f:
                metadados = json.load(f)
            for m in metadados:
                conn.execute("""
                    INSERT INTO edital_info (edital_nome, cargo, orgao, banca, vagas, subsidio, inscricoes,
                        data_prova_objetiva, data_prova_discursiva, horario, local_prova, taxa_inscricao, link_edital, observacoes)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """, (m.get("edital_nome", ""), m.get("cargo", ""), m.get("orgao", ""), m.get("banca", ""),
                      m.get("vagas", ""), m.get("subsidio", ""), m.get("inscricoes", ""),
                      m.get("data_prova_objetiva", ""), m.get("data_prova_discursiva", ""),
                      m.get("horario", ""), m.get("local_prova", ""), m.get("taxa_inscricao", ""),
                      m.get("link_edital", ""), m.get("observacoes", "")))
            log.info(f"Seeded {len(metadados)} edital_info entries")

    conn.commit()


def rebuild_search_index(conn):
    """Rebuild the full-text search index."""
    conn.execute("DELETE FROM search_index")

    # Edital topics
    result = conn.execute("SELECT id, materia, topico FROM edital")
    for r in result.fetchall():
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (%s, %s, %s, %s)",
            ("edital", str(r[0]), r[1], r[2])
        )

    # Questões
    result = conn.execute("SELECT id, materia, enunciado FROM questoes")
    for r in result.fetchall():
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (%s, %s, %s, %s)",
            ("questao", str(r[0]), r[1], r[2])
        )

    # Flashcards
    result = conn.execute("SELECT id, pergunta, resposta FROM flashcards")
    for r in result.fetchall():
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (%s, %s, %s, %s)",
            ("flashcard", str(r[0]), r[1], r[2])
        )

    # Notas
    result = conn.execute("SELECT id, conteudo FROM notas_pdf")
    for r in result.fetchall():
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (%s, %s, %s, %s)",
            ("nota", str(r[0]), "", r[1])
        )

    conn.commit()
    log.info("Search index rebuilt (PostgreSQL)")


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_db():
    """Initialize the PostgreSQL database: tables, indexes, and default data."""
    pool = _get_pool()
    raw_conn = pool.getconn()
    conn = PgConnectionWrapper(raw_conn)
    try:
        _create_tables(conn)
        _create_indexes(conn)
        _create_search_table(conn)
        _seed_defaults(conn)
        rebuild_search_index(conn)
        conn.commit()
        log.info("PostgreSQL database initialized")
    except Exception as e:
        conn.rollback()
        log.error(f"PostgreSQL init_db failed: {e}")
        raise
    finally:
        conn.close()

"""Migrações de schema (ALTER TABLE) para o banco de dados.

Versionamento: cada migration tem um número sequencial. Apenas migrations
com número > versão atual são executadas. A tabela schema_version registra
quais já foram aplicadas.
"""
from datetime import datetime

from logger import log


# ============================================================
# REGISTRO DE MIGRATIONS — cada entrada é (número, função)
# ============================================================

def _m01_edital_nome(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN edital_nome TEXT DEFAULT 'Geral'")

def _m02_edital_cargo(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN cargo TEXT DEFAULT ''")

def _m03_edital_pdf_link(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN pdf_link TEXT DEFAULT ''")

def _m04_edital_pdf_pagina(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN pdf_pagina INTEGER DEFAULT 0")

def _m05_edital_arquivado(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN arquivado INTEGER DEFAULT 0")

def _m06_edital_revisao(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN proxima_revisao TEXT DEFAULT ''")
    conn.execute("ALTER TABLE edital ADD COLUMN intervalo_revisao INTEGER DEFAULT 1")

def _m07_questoes_banca(conn):
    conn.execute("ALTER TABLE questoes ADD COLUMN banca TEXT DEFAULT ''")

def _m08_questoes_ano(conn):
    conn.execute("ALTER TABLE questoes ADD COLUMN ano TEXT DEFAULT ''")

def _m09_flashcards_sm2(conn):
    conn.execute("ALTER TABLE flashcards ADD COLUMN easiness_factor REAL DEFAULT 2.5")
    conn.execute("ALTER TABLE flashcards ADD COLUMN repetitions INTEGER DEFAULT 0")

def _m10_flashcards_materia(conn):
    conn.execute("ALTER TABLE flashcards ADD COLUMN materia TEXT DEFAULT ''")

def _m11_edital_sm2(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN easiness_factor_edital REAL DEFAULT 2.5")
    conn.execute("ALTER TABLE edital ADD COLUMN repetitions_edital INTEGER DEFAULT 0")

def _m12_users_plano(conn):
    conn.execute("ALTER TABLE users ADD COLUMN plano TEXT DEFAULT 'free'")
    conn.execute("ALTER TABLE users ADD COLUMN plano_expira TEXT DEFAULT ''")

def _m13_metas_sumulas(conn):
    conn.execute("ALTER TABLE metas_config ADD COLUMN meta_sumulas INTEGER DEFAULT 0")

def _m14_streaks_sumulas(conn):
    conn.execute("ALTER TABLE streaks ADD COLUMN sumulas_revisadas INTEGER DEFAULT 0")

def _m15_streak_freeze(conn):
    conn.execute("ALTER TABLE metas_config ADD COLUMN streak_freezes_available INTEGER DEFAULT 1")
    conn.execute("ALTER TABLE metas_config ADD COLUMN streak_freezes_used INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE metas_config ADD COLUMN last_freeze_earned TEXT DEFAULT ''")

def _m16_sessoes_created_at(conn):
    conn.execute("ALTER TABLE sessoes_estudo ADD COLUMN created_at TEXT DEFAULT ''")

def _m17_flashcards_stability(conn):
    conn.execute("ALTER TABLE flashcards ADD COLUMN stability REAL DEFAULT 0")

def _m18_flashcards_difficulty(conn):
    conn.execute("ALTER TABLE flashcards ADD COLUMN difficulty REAL DEFAULT 0")

def _m19_flashcards_fsrs_state(conn):
    conn.execute("ALTER TABLE flashcards ADD COLUMN fsrs_state INTEGER DEFAULT 0")

def _m20_edital_stability(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN stability_edital REAL DEFAULT 0")

def _m21_edital_difficulty(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN difficulty_edital REAL DEFAULT 0")

def _m22_edital_fsrs_state(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN fsrs_state_edital INTEGER DEFAULT 0")

def _m23_sumulas_stability(conn):
    conn.execute("ALTER TABLE sumulas ADD COLUMN stability REAL DEFAULT 0")

def _m24_sumulas_difficulty(conn):
    conn.execute("ALTER TABLE sumulas ADD COLUMN difficulty_sumulas REAL DEFAULT 0")

def _m25_sumulas_fsrs_state(conn):
    conn.execute("ALTER TABLE sumulas ADD COLUMN fsrs_state INTEGER DEFAULT 0")

def _m26_metas_desired_retention(conn):
    conn.execute("ALTER TABLE metas_config ADD COLUMN desired_retention REAL DEFAULT 0.9")

def _m27_push_subscriptions(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            endpoint TEXT NOT NULL UNIQUE,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user_id ON push_subscriptions(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_subscriptions_endpoint ON push_subscriptions(endpoint)")

def _m28_notification_preferences(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_preferences (
            user_id INTEGER PRIMARY KEY,
            streak_reminders INTEGER DEFAULT 1,
            flashcard_reminders INTEGER DEFAULT 1,
            exam_reminders INTEGER DEFAULT 1,
            challenge_reminders INTEGER DEFAULT 1,
            quiet_hours_start INTEGER DEFAULT 22,
            quiet_hours_end INTEGER DEFAULT 7
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_preferences_user_id ON notification_preferences(user_id)")

def _m29_fix_notification_preferences(conn):
    # Fix old schema (had streak_risk instead of streak_reminders)
    try:
        conn.execute("SELECT streak_reminders FROM notification_preferences LIMIT 1")
    except Exception:
        conn.execute("DROP TABLE IF EXISTS notification_preferences")
        conn.execute("""
            CREATE TABLE notification_preferences (
                user_id INTEGER PRIMARY KEY,
                streak_reminders INTEGER DEFAULT 1,
                flashcard_reminders INTEGER DEFAULT 1,
                exam_reminders INTEGER DEFAULT 1,
                challenge_reminders INTEGER DEFAULT 1,
                quiet_hours_start INTEGER DEFAULT 22,
                quiet_hours_end INTEGER DEFAULT 7
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_preferences_user_id ON notification_preferences(user_id)")

def _m30_notification_log(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tag TEXT NOT NULL,
            title TEXT DEFAULT '',
            body TEXT DEFAULT '',
            sent_at TEXT NOT NULL,
            success INTEGER DEFAULT 1
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_log_user_id ON notification_log(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_log_sent_at ON notification_log(sent_at)")

def _m31_edital_mastery(conn):
    conn.execute("ALTER TABLE edital ADD COLUMN mastery_level REAL DEFAULT 0")
    conn.execute("ALTER TABLE edital ADD COLUMN mastery_updated_at TEXT DEFAULT ''")

def _m32_multi_user_isolation(conn):
    _migrate_user_id(conn)

def _m33_users_username(conn):
    conn.execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''")

def _m34_users_role(conn):
    conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
    conn.execute("UPDATE users SET role = 'admin' WHERE id = 1")

def _m35_users_liga(conn):
    conn.execute("ALTER TABLE users ADD COLUMN liga TEXT DEFAULT 'bronze'")

def _m36_erros_revisao(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS erros_revisao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            questao_id INTEGER NOT NULL,
            resposta_id INTEGER NOT NULL,
            intervalo_atual INTEGER DEFAULT 1,
            proxima_revisao TEXT NOT NULL,
            revisoes_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT '',
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_erros_revisao_user_id ON erros_revisao(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_erros_revisao_proxima ON erros_revisao(user_id, proxima_revisao)")

def _m37_simulados_tipo(conn):
    conn.execute("ALTER TABLE simulados ADD COLUMN tipo TEXT DEFAULT 'normal'")

def _m38_questoes_respostas_confianca(conn):
    """Migration 38: confidence field for confidence-based repetition (A2)."""
    try:
        conn.execute("SELECT confianca FROM questoes_respostas LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE questoes_respostas ADD COLUMN confianca INTEGER DEFAULT NULL")

def _m39_elaboration_log(conn):
    """Migration 39: elaboration log table for elaboration prompts (A3)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS elaboration_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            flashcard_id INTEGER,
            questao_id INTEGER,
            prompt_tipo TEXT NOT NULL,
            resposta_usuario TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elaboration_log_user_id ON elaboration_log(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elaboration_log_flashcard ON elaboration_log(flashcard_id)")


def _m40_erros_revisao_fsrs(conn):
    """Migration 40: Add FSRS fields to erros_revisao for spaced repetition (B1)."""
    conn.execute("ALTER TABLE erros_revisao ADD COLUMN stability REAL DEFAULT NULL")
    conn.execute("ALTER TABLE erros_revisao ADD COLUMN difficulty REAL DEFAULT NULL")
    conn.execute("ALTER TABLE erros_revisao ADD COLUMN fsrs_state INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE erros_revisao ADD COLUMN reps INTEGER DEFAULT 0")
    conn.execute("ALTER TABLE erros_revisao ADD COLUMN last_review TEXT DEFAULT NULL")


def _m41_session_metrics(conn):
    """Migration 41: Create session_metrics table for intra-session fatigue detection (B3)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            session_id TEXT NOT NULL,
            questao_num INTEGER NOT NULL,
            tempo_ms INTEGER NOT NULL,
            acertou INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_session_metrics_user_session ON session_metrics(user_id, session_id)")


def _m42_generation_responses(conn):
    """Migration 42: Create generation_responses table for Generation Mode (C2)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generation_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            questao_id INTEGER NOT NULL,
            resposta_digitada TEXT NOT NULL,
            resposta_correta TEXT NOT NULL,
            match_score REAL DEFAULT 0.0,
            acertou INTEGER NOT NULL DEFAULT 0,
            tempo_ms INTEGER DEFAULT 0,
            modo TEXT DEFAULT 'geracao',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_responses_user ON generation_responses(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_generation_responses_questao ON generation_responses(questao_id)")


def _m43_sessao_adaptativa(conn):
    """Migration 43: Create sessao_adaptativa and sessao_adaptativa_respostas tables for CAT (C1)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessao_adaptativa (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            session_id TEXT NOT NULL UNIQUE,
            materia TEXT DEFAULT '',
            theta REAL DEFAULT 0.0,
            questoes_respondidas INTEGER DEFAULT 0,
            acertos INTEGER DEFAULT 0,
            dificuldade_atual TEXT DEFAULT 'Médio',
            status TEXT DEFAULT 'ativa',
            started_at TEXT NOT NULL,
            finished_at TEXT DEFAULT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessao_adaptativa_user ON sessao_adaptativa(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessao_adaptativa_session ON sessao_adaptativa(session_id)")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessao_adaptativa_respostas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            questao_id INTEGER NOT NULL,
            acertou INTEGER NOT NULL DEFAULT 0,
            tempo_ms INTEGER DEFAULT 0,
            dificuldade_questao TEXT DEFAULT 'Médio',
            theta_pos REAL DEFAULT 0.0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessao_adapt_resp_session ON sessao_adaptativa_respostas(session_id)")


# Lista ordenada de todas as migrations
MIGRATIONS = [
    (1, _m01_edital_nome),
    (2, _m02_edital_cargo),
    (3, _m03_edital_pdf_link),
    (4, _m04_edital_pdf_pagina),
    (5, _m05_edital_arquivado),
    (6, _m06_edital_revisao),
    (7, _m07_questoes_banca),
    (8, _m08_questoes_ano),
    (9, _m09_flashcards_sm2),
    (10, _m10_flashcards_materia),
    (11, _m11_edital_sm2),
    (12, _m12_users_plano),
    (13, _m13_metas_sumulas),
    (14, _m14_streaks_sumulas),
    (15, _m15_streak_freeze),
    (16, _m16_sessoes_created_at),
    (17, _m17_flashcards_stability),
    (18, _m18_flashcards_difficulty),
    (19, _m19_flashcards_fsrs_state),
    (20, _m20_edital_stability),
    (21, _m21_edital_difficulty),
    (22, _m22_edital_fsrs_state),
    (23, _m23_sumulas_stability),
    (24, _m24_sumulas_difficulty),
    (25, _m25_sumulas_fsrs_state),
    (26, _m26_metas_desired_retention),
    (27, _m27_push_subscriptions),
    (28, _m28_notification_preferences),
    (29, _m29_fix_notification_preferences),
    (30, _m30_notification_log),
    (31, _m31_edital_mastery),
    (32, _m32_multi_user_isolation),
    (33, _m33_users_username),
    (34, _m34_users_role),
    (35, _m35_users_liga),
    (36, _m36_erros_revisao),
    (37, _m37_simulados_tipo),
    (38, _m38_questoes_respostas_confianca),
    (39, _m39_elaboration_log),
    (40, _m40_erros_revisao_fsrs),
    (41, _m41_session_metrics),
    (42, _m42_generation_responses),
    (43, _m43_sessao_adaptativa),
]


# ============================================================
# EXECUTOR DE MIGRATIONS COM VERSIONAMENTO
# ============================================================

def _ensure_schema_version_table(conn) -> bool:
    """Garante que a tabela schema_version existe. Retorna True se foi recém-criada."""
    # Verifica se a tabela existe
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_version'"
    ).fetchone()
    if exists:
        return False
    # Cria a tabela (primeiro startup após update ou banco novo)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return True


def _is_fresh_database(conn) -> bool:
    """Detecta se é um banco novo (tables.py já criou tudo corretamente).

    Heurística: se schema_version foi recém-criada E as tabelas já têm
    as colunas mais recentes, é banco novo — não precisa rodar migrations.
    """
    try:
        # Verifica coluna de uma migration tardia (tipo em simulados = migration 37)
        conn.execute("SELECT tipo FROM simulados LIMIT 1")
        # Se chegou aqui, as tabelas já estão atualizadas
        return True
    except Exception:
        return False


def _get_current_version(conn) -> int:
    """Retorna a versão atual do schema (MAX(version) da schema_version)."""
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    return row[0] if row[0] is not None else 0


def _run_migrations(conn):
    """Executa migrações de schema com versionamento."""
    table_just_created = _ensure_schema_version_table(conn)

    if table_just_created:
        # Caso 1: Banco NOVO (tables.py criou tudo) — marca todas como aplicadas
        if _is_fresh_database(conn):
            now = datetime.now().isoformat()
            for version, _ in MIGRATIONS:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                    (version, now)
                )
            conn.commit()
            log.info(f"Fresh database detected — marked {len(MIGRATIONS)} migrations as applied")
            return
        # Caso 2: Banco EXISTENTE sem schema_version (primeiro startup após update)
        # → roda migrations normalmente (cada uma com try/except individual)
        log.info("Existing database without schema_version — running migrations with compatibility mode")
        _run_migrations_compat(conn)
        return

    # Caso 3: Banco com schema_version — executa apenas migrations pendentes
    current_version = _get_current_version(conn)
    pending = [(v, fn) for v, fn in MIGRATIONS if v > current_version]

    if not pending:
        return

    log.info(f"Running {len(pending)} pending migration(s) (current version: {current_version})")
    now = datetime.now().isoformat()
    for version, migration_fn in pending:
        try:
            migration_fn(conn)
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, now)
            )
            conn.commit()
            log.info(f"Migration {version} applied: {migration_fn.__name__}")
        except Exception as e:
            log.warning(f"Migration {version} ({migration_fn.__name__}) skipped: {e}")
            # Registra mesmo assim para não tentar novamente (coluna já existe, etc.)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, now)
            )
            conn.commit()


def _run_migrations_compat(conn):
    """Modo retrocompatível: roda todas as migrations com try/except (banco existente sem versão).

    Após rodar, registra todas na schema_version.
    """
    now = datetime.now().isoformat()
    applied = 0
    skipped = 0

    for version, migration_fn in MIGRATIONS:
        try:
            migration_fn(conn)
            applied += 1
            log.info(f"Migration {version} applied: {migration_fn.__name__}")
        except Exception:
            skipped += 1
        # Registra independentemente (se falhou, é porque já existia)
        conn.execute(
            "INSERT OR IGNORE INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, now)
        )

    conn.commit()
    log.info(f"Compat mode complete: {applied} applied, {skipped} skipped (already existed)")


# ============================================================
# HELPER: Multi-user isolation (migration 32)
# ============================================================

def _migrate_user_id(conn):
    """Adiciona coluna user_id em todas as tabelas que precisam de isolamento por usuário."""
    tables_needing_user_id = [
        "edital", "flashcards", "questoes", "questoes_respostas",
        "simulados", "simulado_questoes", "ciclo_estudos", "sessoes_estudo",
        "streaks", "metas_config", "notas_pdf", "notas_topico",
        "bookmarks_pdf", "cadernos", "caderno_itens", "feynman",
        "desafios", "planejador_semanal", "calendario_personalizado",
        "calendario_atividades", "calendario_streaks", "resumos",
        "sumulas", "progress", "edital_info",
    ]

    for table in tables_needing_user_id:
        try:
            conn.execute(f"SELECT user_id FROM {table} LIMIT 1")
        except Exception:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1")
                log.info(f"Migration: added column user_id to {table}")
            except Exception:
                pass

    # Criar índice composto para user_id nas tabelas mais consultadas
    index_tables = [
        "edital", "flashcards", "questoes", "questoes_respostas",
        "sessoes_estudo", "streaks", "simulados", "ciclo_estudos",
        "sumulas", "metas_config", "progress",
    ]
    for table in index_tables:
        try:
            conn.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_user_id ON {table}(user_id)")
        except Exception:
            pass

    # Garantir que metas_config tem registro para user_id=1
    existing = conn.execute("SELECT id FROM metas_config WHERE user_id = 1 LIMIT 1").fetchone()
    if not existing:
        conn.execute("UPDATE metas_config SET user_id = 1 WHERE user_id IS NULL OR user_id = 0")

    # ========== FIX: streaks UNIQUE constraint deve ser (user_id, data), não apenas (data) ==========
    table_info = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='streaks'").fetchone()
    if table_info and "UNIQUE(user_id, data)" not in (table_info[0] or ""):
        try:
            conn.execute("ALTER TABLE streaks RENAME TO _streaks_old")
            conn.execute("""
                CREATE TABLE streaks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    data TEXT NOT NULL,
                    horas_estudadas REAL DEFAULT 0.0,
                    questoes_resolvidas INTEGER DEFAULT 0,
                    flashcards_revisados INTEGER DEFAULT 0,
                    sumulas_revisadas INTEGER DEFAULT 0,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    UNIQUE(user_id, data)
                )
            """)
            conn.execute("""
                INSERT INTO streaks (id, data, horas_estudadas, questoes_resolvidas, flashcards_revisados, user_id)
                SELECT id, data, horas_estudadas, questoes_resolvidas, flashcards_revisados,
                       COALESCE(user_id, 1) FROM _streaks_old
            """)
            conn.execute("DROP TABLE _streaks_old")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_streaks_user_id ON streaks(user_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_streaks_data ON streaks(data)")
            log.info("Migration: streaks UNIQUE constraint fixed to (user_id, data)")
        except Exception:
            pass

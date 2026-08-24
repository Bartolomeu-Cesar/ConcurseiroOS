"""Migrações de schema (ALTER TABLE) para o banco de dados."""
from logger import log


def _run_migrations(conn):
    """Executa migrações de schema (ALTER TABLE)."""
    # Adicionar colunas no edital se não existirem
    try:
        conn.execute("SELECT edital_nome FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN edital_nome TEXT DEFAULT 'Geral'")
        log.info("Migration: added column edital_nome to edital")

    try:
        conn.execute("SELECT cargo FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN cargo TEXT DEFAULT ''")
        log.info("Migration: added column cargo to edital")

    try:
        conn.execute("SELECT pdf_link FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN pdf_link TEXT DEFAULT ''")
        log.info("Migration: added column pdf_link to edital")

    try:
        conn.execute("SELECT pdf_pagina FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN pdf_pagina INTEGER DEFAULT 0")
        log.info("Migration: added column pdf_pagina to edital")

    try:
        conn.execute("SELECT arquivado FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN arquivado INTEGER DEFAULT 0")
        log.info("Migration: added column arquivado to edital")

    try:
        conn.execute("SELECT proxima_revisao FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN proxima_revisao TEXT DEFAULT ''")
        conn.execute("ALTER TABLE edital ADD COLUMN intervalo_revisao INTEGER DEFAULT 1")
        log.info("Migration: added columns proxima_revisao, intervalo_revisao to edital")

    # Lote E: coluna banca nas questões
    try:
        conn.execute("SELECT banca FROM questoes LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE questoes ADD COLUMN banca TEXT DEFAULT ''")
        log.info("Migration: added column banca to questoes")

    # Coluna ano nas questões (ano da prova, para CSV import)
    try:
        conn.execute("SELECT ano FROM questoes LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE questoes ADD COLUMN ano TEXT DEFAULT ''")
            log.info("Migration: added column ano to questoes")
        except Exception:
            pass

    # Lote D: SM-2 para flashcards
    try:
        conn.execute("SELECT easiness_factor FROM flashcards LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE flashcards ADD COLUMN easiness_factor REAL DEFAULT 2.5")
        conn.execute("ALTER TABLE flashcards ADD COLUMN repetitions INTEGER DEFAULT 0")
        log.info("Migration: added SM-2 columns to flashcards")

    # Flashcards: coluna materia
    try:
        conn.execute("SELECT materia FROM flashcards LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE flashcards ADD COLUMN materia TEXT DEFAULT ''")
        log.info("Migration: added column materia to flashcards")

    # Lote D: SM-2 para edital (revisão de tópicos)
    try:
        conn.execute("SELECT easiness_factor_edital FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN easiness_factor_edital REAL DEFAULT 2.5")
        conn.execute("ALTER TABLE edital ADD COLUMN repetitions_edital INTEGER DEFAULT 0")
        log.info("Migration: added SM-2 columns to edital")

    # Auth: colunas de plano
    try:
        conn.execute("SELECT plano FROM users LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN plano TEXT DEFAULT 'free'")
            conn.execute("ALTER TABLE users ADD COLUMN plano_expira TEXT DEFAULT ''")
            log.info("Migration: added plano columns to users")
        except Exception:
            pass

    # Meta de súmulas diárias (concursos jurídicos)
    try:
        conn.execute("SELECT meta_sumulas FROM metas_config LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE metas_config ADD COLUMN meta_sumulas INTEGER DEFAULT 0")
            log.info("Migration: added column meta_sumulas to metas_config")
        except Exception:
            pass

    # Contador de súmulas revisadas no streak diário
    try:
        conn.execute("SELECT sumulas_revisadas FROM streaks LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE streaks ADD COLUMN sumulas_revisadas INTEGER DEFAULT 0")
            log.info("Migration: added column sumulas_revisadas to streaks")
        except Exception:
            pass

    # Streak Freeze: colunas para congelar streak
    try:
        conn.execute("SELECT streak_freezes_available FROM metas_config LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE metas_config ADD COLUMN streak_freezes_available INTEGER DEFAULT 1")
            conn.execute("ALTER TABLE metas_config ADD COLUMN streak_freezes_used INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE metas_config ADD COLUMN last_freeze_earned TEXT DEFAULT ''")
            log.info("Migration: added streak_freeze columns to metas_config")
        except Exception:
            pass

    # Sessões de estudo: timestamp para badges Night Owl / Early Bird
    try:
        conn.execute("SELECT created_at FROM sessoes_estudo LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE sessoes_estudo ADD COLUMN created_at TEXT DEFAULT ''")
            log.info("Migration: added column created_at to sessoes_estudo")
        except Exception:
            pass

    # ========== FSRS columns for flashcards ==========
    try:
        conn.execute("SELECT stability FROM flashcards LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE flashcards ADD COLUMN stability REAL DEFAULT 0")
            log.info("Migration: added column stability to flashcards")
        except Exception:
            pass

    try:
        conn.execute("SELECT difficulty FROM flashcards LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE flashcards ADD COLUMN difficulty REAL DEFAULT 0")
            log.info("Migration: added column difficulty to flashcards")
        except Exception:
            pass

    try:
        conn.execute("SELECT fsrs_state FROM flashcards LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE flashcards ADD COLUMN fsrs_state INTEGER DEFAULT 0")
            log.info("Migration: added column fsrs_state to flashcards")
        except Exception:
            pass

    # ========== FSRS columns for edital ==========
    try:
        conn.execute("SELECT stability_edital FROM edital LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE edital ADD COLUMN stability_edital REAL DEFAULT 0")
            log.info("Migration: added column stability_edital to edital")
        except Exception:
            pass

    try:
        conn.execute("SELECT difficulty_edital FROM edital LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE edital ADD COLUMN difficulty_edital REAL DEFAULT 0")
            log.info("Migration: added column difficulty_edital to edital")
        except Exception:
            pass

    try:
        conn.execute("SELECT fsrs_state_edital FROM edital LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE edital ADD COLUMN fsrs_state_edital INTEGER DEFAULT 0")
            log.info("Migration: added column fsrs_state_edital to edital")
        except Exception:
            pass

    # ========== FSRS columns for sumulas ==========
    try:
        conn.execute("SELECT stability FROM sumulas LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE sumulas ADD COLUMN stability REAL DEFAULT 0")
            log.info("Migration: added column stability to sumulas")
        except Exception:
            pass

    try:
        conn.execute("SELECT difficulty_sumulas FROM sumulas LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE sumulas ADD COLUMN difficulty_sumulas REAL DEFAULT 0")
            log.info("Migration: added column difficulty_sumulas to sumulas")
        except Exception:
            pass

    try:
        conn.execute("SELECT fsrs_state FROM sumulas LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE sumulas ADD COLUMN fsrs_state INTEGER DEFAULT 0")
            log.info("Migration: added column fsrs_state to sumulas")
        except Exception:
            pass

    # ========== desired_retention in metas_config ==========
    try:
        conn.execute("SELECT desired_retention FROM metas_config LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE metas_config ADD COLUMN desired_retention REAL DEFAULT 0.9")
            log.info("Migration: added column desired_retention to metas_config")
        except Exception:
            pass

    # ========== Push Notification tables ==========
    try:
        conn.execute("SELECT id FROM push_subscriptions LIMIT 1")
    except Exception:
        try:
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
            log.info("Migration: created table push_subscriptions")
        except Exception:
            pass

    try:
        conn.execute("SELECT id FROM notification_preferences LIMIT 1")
    except Exception:
        try:
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
            log.info("Migration: created table notification_preferences")
        except Exception:
            pass

    # Fix old notification_preferences schema (had streak_risk instead of streak_reminders)
    try:
        conn.execute("SELECT streak_reminders FROM notification_preferences LIMIT 1")
    except Exception:
        # Old schema detected — recreate table with correct columns
        try:
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
            log.info("Migration: recreated notification_preferences with correct column names")
        except Exception:
            pass

    try:
        conn.execute("SELECT id FROM notification_log LIMIT 1")
    except Exception:
        try:
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
            log.info("Migration: created table notification_log")
        except Exception:
            pass

    # Mastery System: nível de domínio por tópico
    try:
        conn.execute("SELECT mastery_level FROM edital LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE edital ADD COLUMN mastery_level REAL DEFAULT 0")
            conn.execute("ALTER TABLE edital ADD COLUMN mastery_updated_at TEXT DEFAULT ''")
            log.info("Migration: added mastery columns to edital")
        except Exception:
            pass

    # ========== MULTI-USER ISOLATION: user_id em todas as tabelas ==========
    _migrate_user_id(conn)

    # ========== SOCIAL: username na tabela users ==========
    try:
        conn.execute("SELECT username FROM users LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN username TEXT DEFAULT ''")
            log.info("Migration: added column username to users")
        except Exception:
            pass

    # ========== ROLE: admin/user na tabela users ==========
    try:
        conn.execute("SELECT role FROM users LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
            conn.execute("UPDATE users SET role = 'admin' WHERE id = 1")
            log.info("Migration: added column role to users (id=1 → admin)")
        except Exception:
            pass

    # Liga column in users table
    try:
        conn.execute("SELECT liga FROM users LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE users ADD COLUMN liga TEXT DEFAULT 'bronze'")
            log.info("Migration: added column liga to users")
        except Exception:
            pass


    # ========== CADERNO DE ERROS: tabela erros_revisao (spaced repetition) ==========
    try:
        conn.execute("SELECT id FROM erros_revisao LIMIT 1")
    except Exception:
        try:
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
            log.info("Migration: created table erros_revisao")
        except Exception:
            pass


    # ========== SIMULADO CRONOMETRADO: tipo column ==========
    try:
        conn.execute("SELECT tipo FROM simulados LIMIT 1")
    except Exception:
        try:
            conn.execute("ALTER TABLE simulados ADD COLUMN tipo TEXT DEFAULT 'normal'")
            log.info("Migration: added column tipo to simulados")
        except Exception:
            pass


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
        # Atualizar registros existentes sem user_id
        conn.execute("UPDATE metas_config SET user_id = 1 WHERE user_id IS NULL OR user_id = 0")

    # ========== FIX: streaks UNIQUE constraint deve ser (user_id, data), não apenas (data) ==========
    # Verifica se o constraint atual é o antigo (data UNIQUE)
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

    conn.commit()

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from logger import log
from settings import settings

DB_PATH = settings.DB_PATH


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    try:
        yield conn
    finally:
        conn.close()


def get_db_session() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency que fornece uma conexão ao banco de dados."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA cache_size=-4000")  # 4MB cache
    try:
        yield conn
    finally:
        conn.close()


def rebuild_search_index(conn):
    """Reconstrói o índice FTS5 com todos os dados."""
    conn.execute("DELETE FROM search_index")

    # Tópicos do edital
    rows = conn.execute("SELECT id, materia, topico FROM edital").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (?, ?, ?, ?)",
            ("edital", str(r[0]), r[1], r[2])
        )

    # Questões
    rows = conn.execute("SELECT id, materia, enunciado FROM questoes").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (?, ?, ?, ?)",
            ("questao", str(r[0]), r[1], r[2])
        )

    # Flashcards
    rows = conn.execute("SELECT id, pergunta, resposta FROM flashcards").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (?, ?, ?, ?)",
            ("flashcard", str(r[0]), r[1], r[2])
        )

    # Notas
    rows = conn.execute("SELECT id, conteudo FROM notas_pdf").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content) VALUES (?, ?, ?, ?)",
            ("nota", str(r[0]), "", r[1])
        )

    conn.commit()
    log.info("Search index rebuilt")


def _create_tables(conn):
    """Cria todas as tabelas do sistema."""
    # Tabela de progresso de PDFs
    conn.execute("""
        CREATE TABLE IF NOT EXISTS progress (
            path TEXT PRIMARY KEY,
            current_page INTEGER DEFAULT 1,
            total_pages INTEGER DEFAULT 1
        )
    """)

    # Edital verticalizado
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edital (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_nome TEXT DEFAULT 'Geral',
            cargo TEXT DEFAULT '',
            materia TEXT NOT NULL,
            topico TEXT NOT NULL,
            status TEXT DEFAULT 'Não Iniciado',
            horas_estudadas REAL DEFAULT 0.0
        )
    """)

    # Flashcards SRS
    conn.execute("""
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pergunta TEXT NOT NULL,
            resposta TEXT NOT NULL,
            proxima_revisao TEXT NOT NULL,
            intervalo_dias INTEGER DEFAULT 1
        )
    """)

    # Banco de Questões
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            created_at TEXT NOT NULL
        )
    """)

    # Respostas do usuário nas questões
    conn.execute("""
        CREATE TABLE IF NOT EXISTS questoes_respostas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            questao_id INTEGER NOT NULL,
            resposta_usuario TEXT NOT NULL,
            acertou INTEGER NOT NULL,
            tempo_segundos INTEGER DEFAULT 0,
            data TEXT NOT NULL,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)

    # Simulados
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            tempo_limite_min INTEGER DEFAULT 60,
            status TEXT DEFAULT 'pendente',
            nota REAL DEFAULT 0.0,
            total_questoes INTEGER DEFAULT 0,
            acertos INTEGER DEFAULT 0,
            tempo_gasto_seg INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            finalizado_at TEXT DEFAULT ''
        )
    """)

    # Questões vinculadas a simulados
    conn.execute("""
        CREATE TABLE IF NOT EXISTS simulado_questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            simulado_id INTEGER NOT NULL,
            questao_id INTEGER NOT NULL,
            ordem INTEGER DEFAULT 0,
            resposta_usuario TEXT DEFAULT '',
            acertou INTEGER DEFAULT -1,
            FOREIGN KEY (simulado_id) REFERENCES simulados(id),
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)

    # Ciclo de Estudos
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ciclo_estudos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            materia TEXT NOT NULL,
            horas_alvo REAL DEFAULT 1.0,
            horas_cumpridas REAL DEFAULT 0.0,
            ordem INTEGER DEFAULT 0,
            ativo INTEGER DEFAULT 1
        )
    """)

    # Registro de sessões de estudo (alimenta dashboard)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessoes_estudo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            materia TEXT NOT NULL,
            horas REAL NOT NULL,
            data TEXT NOT NULL,
            tipo TEXT DEFAULT 'edital'
        )
    """)

    # Streaks
    conn.execute("""
        CREATE TABLE IF NOT EXISTS streaks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT UNIQUE NOT NULL,
            horas_estudadas REAL DEFAULT 0.0,
            questoes_resolvidas INTEGER DEFAULT 0,
            flashcards_revisados INTEGER DEFAULT 0
        )
    """)

    # Metas diárias
    conn.execute("""
        CREATE TABLE IF NOT EXISTS metas_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            meta_horas REAL DEFAULT 3.0,
            meta_questoes INTEGER DEFAULT 30,
            meta_flashcards INTEGER DEFAULT 10,
            meta_paginas INTEGER DEFAULT 20
        )
    """)

    # Notas/Anotações por PDF
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notas_pdf (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_path TEXT NOT NULL,
            pagina INTEGER DEFAULT 1,
            conteudo TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Metadados dos editais (datas, locais, horários)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS edital_info (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            observacoes TEXT DEFAULT ''
        )
    """)

    # Planejador semanal
    conn.execute("""
        CREATE TABLE IF NOT EXISTS planejador_semanal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dia_semana INTEGER NOT NULL,
            materia TEXT NOT NULL,
            horas REAL DEFAULT 1.0
        )
    """)

    # Notas por tópico do edital
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notas_topico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_id INTEGER NOT NULL,
            conteudo TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Cadernos
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cadernos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS caderno_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caderno_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            FOREIGN KEY (caderno_id) REFERENCES cadernos(id)
        )
    """)

    # Bookmarks PDF
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bookmarks_pdf (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_path TEXT NOT NULL,
            pagina INTEGER NOT NULL,
            label TEXT DEFAULT '',
            cor TEXT DEFAULT 'blue',
            created_at TEXT NOT NULL
        )
    """)

    # Feynman
    conn.execute("""
        CREATE TABLE IF NOT EXISTS feynman (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_id INTEGER NOT NULL,
            explicacao TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Desafios
    conn.execute("""
        CREATE TABLE IF NOT EXISTS desafios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            titulo TEXT NOT NULL,
            meta_tipo TEXT NOT NULL,
            meta_valor INTEGER NOT NULL,
            materia TEXT DEFAULT '',
            progresso INTEGER DEFAULT 0,
            dias INTEGER DEFAULT 7,
            created_at TEXT NOT NULL,
            finalizado INTEGER DEFAULT 0
        )
    """)

    # Resumos (Elaboration Strategy)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS resumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            edital_id INTEGER NOT NULL,
            resumo TEXT NOT NULL,
            tipo TEXT DEFAULT 'livre',
            created_at TEXT NOT NULL
        )
    """)

    # Calendário personalizado
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_personalizado (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dia_semana INTEGER NOT NULL,
            materia TEXT NOT NULL,
            topicos TEXT DEFAULT '',
            tempo_min INTEGER DEFAULT 60,
            tipo TEXT DEFAULT 'estudo',
            ordem INTEGER DEFAULT 0
        )
    """)

    # Atividades do calendário concluídas
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_atividades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT NOT NULL,
            dia_semana INTEGER NOT NULL,
            materia TEXT DEFAULT '',
            tipo TEXT DEFAULT 'estudo',
            tempo_min INTEGER DEFAULT 0,
            concluida INTEGER DEFAULT 0,
            concluida_at TEXT DEFAULT ''
        )
    """)

    # Streak do calendário (dias que completou 100% do planejado)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS calendario_streaks (
            data TEXT PRIMARY KEY,
            total_atividades INTEGER DEFAULT 0,
            concluidas INTEGER DEFAULT 0,
            pct_conclusao REAL DEFAULT 0.0,
            xp_bonus INTEGER DEFAULT 0
        )
    """)

    # ========== LEAGUES ==========
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leagues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'bronze',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS league_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            league_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            weekly_xp INTEGER DEFAULT 0,
            rank INTEGER DEFAULT 0,
            promoted INTEGER DEFAULT 0,
            demoted INTEGER DEFAULT 0,
            is_bot INTEGER DEFAULT 0,
            bot_name TEXT DEFAULT '',
            joined_at TEXT DEFAULT '',
            FOREIGN KEY (league_id) REFERENCES leagues(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS league_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            data TEXT NOT NULL,
            tokens_used INTEGER DEFAULT 0,
            requests_count INTEGER DEFAULT 0,
            UNIQUE(user_id, data)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_a INTEGER NOT NULL,
            user_b INTEGER NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT DEFAULT 'membro',
            joined_at TEXT NOT NULL,
            FOREIGN KEY (group_id) REFERENCES study_groups(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS group_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            meta_tipo TEXT NOT NULL,
            meta_valor INTEGER NOT NULL,
            dias INTEGER DEFAULT 7,
            created_at TEXT NOT NULL,
            FOREIGN KEY (group_id) REFERENCES study_groups(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_feed (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            dados TEXT DEFAULT '{}',
            created_at TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_gamification (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            xp INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            badge_name TEXT NOT NULL,
            earned_at TEXT NOT NULL
        )
    """)

    # Usuários
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            nome TEXT DEFAULT '',
            avatar TEXT DEFAULT '',
            password_hash TEXT DEFAULT '',
            email_verified INTEGER DEFAULT 0,
            plano TEXT DEFAULT 'free',
            plano_expira TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            last_login TEXT DEFAULT ''
        )
    """)

    # Códigos de autenticação por email
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            code TEXT NOT NULL,
            tipo TEXT DEFAULT 'login',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used INTEGER DEFAULT 0
        )
    """)

    # Rate limiting para tentativas de verificação
    conn.execute("""
        CREATE TABLE IF NOT EXISTS auth_attempts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            ip TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    # Súmulas (revisão SRS como flashcards)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sumulas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tribunal TEXT NOT NULL,
            numero INTEGER NOT NULL,
            enunciado TEXT NOT NULL,
            tema TEXT DEFAULT '',
            observacao TEXT DEFAULT '',
            vinculante INTEGER DEFAULT 0,
            proxima_revisao TEXT NOT NULL,
            intervalo_dias INTEGER DEFAULT 1,
            easiness_factor REAL DEFAULT 2.5,
            repetitions INTEGER DEFAULT 0
        )
    """)


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
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            conn.execute("CREATE INDEX IF NOT EXISTS idx_notification_preferences_user_id ON notification_preferences(user_id)")
            log.info("Migration: created table notification_preferences")
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

    conn.commit()


def _create_indexes(conn):
    """Cria índices para performance."""
    conn.execute("CREATE INDEX IF NOT EXISTS idx_streaks_data ON streaks(data)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessoes_data ON sessoes_estudo(data)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questoes_respostas_data ON questoes_respostas(data)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questoes_materia ON questoes(materia)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edital_nome_cargo ON edital(edital_nome, cargo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questoes_respostas_questao_id ON questoes_respostas(questao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notas_pdf_path ON notas_pdf(pdf_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_pdf_path ON bookmarks_pdf(pdf_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edital_materia ON edital(materia)")

    # Índices compostos para queries frequentes do dashboard
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessoes_data_materia ON sessoes_estudo(data, materia)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questoes_respostas_data_acertou ON questoes_respostas(data, acertou)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edital_status ON edital(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edital_nome_cargo_status ON edital(edital_nome, cargo, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_proxima_revisao ON flashcards(proxima_revisao)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sumulas_proxima_revisao ON sumulas(proxima_revisao)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sumulas_tribunal ON sumulas(tribunal)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ciclo_ativo ON ciclo_estudos(ativo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questoes_respostas_questao_acertou ON questoes_respostas(questao_id, acertou)")

    # FTS5 Full-Text Search
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
            source,
            source_id,
            title,
            content,
            tokenize='unicode61'
        )
    """)


def _seed_defaults(conn):
    """Insere dados padrão se não existirem."""
    conn.execute("""
        INSERT OR IGNORE INTO metas_config (id, meta_horas, meta_questoes, meta_flashcards, meta_paginas)
        VALUES (1, 3.0, 30, 10, 20)
    """)

    # Seed metadados dos editais (se tabela vazia)
    count = conn.execute("SELECT COUNT(*) FROM edital_info").fetchone()[0]
    if count == 0:
        import json
        import os
        meta_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'editais_metadados.json')
        if os.path.exists(meta_path):
            with open(meta_path, 'r', encoding='utf-8') as f:
                metadados = json.load(f)
            for m in metadados:
                conn.execute("""
                    INSERT INTO edital_info (edital_nome, cargo, orgao, banca, vagas, subsidio, inscricoes,
                        data_prova_objetiva, data_prova_discursiva, horario, local_prova, taxa_inscricao, link_edital, observacoes)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (m.get("edital_nome",""), m.get("cargo",""), m.get("orgao",""), m.get("banca",""),
                      m.get("vagas",""), m.get("subsidio",""), m.get("inscricoes",""),
                      m.get("data_prova_objetiva",""), m.get("data_prova_discursiva",""),
                      m.get("horario",""), m.get("local_prova",""), m.get("taxa_inscricao",""),
                      m.get("link_edital",""), m.get("observacoes","")))
            log.info(f"Seeded {len(metadados)} edital_info entries")


def _create_fts5_triggers(conn):
    """Cria triggers para manter o índice FTS5 atualizado em tempo real."""
    # Edital: INSERT
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_edital_fts_insert AFTER INSERT ON edital
        BEGIN
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('edital', CAST(NEW.id AS TEXT), NEW.materia, NEW.topico);
        END
    """)
    # Edital: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_edital_fts_update AFTER UPDATE OF materia, topico ON edital
        BEGIN
            DELETE FROM search_index WHERE source = 'edital' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('edital', CAST(NEW.id AS TEXT), NEW.materia, NEW.topico);
        END
    """)
    # Edital: DELETE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_edital_fts_delete AFTER DELETE ON edital
        BEGIN
            DELETE FROM search_index WHERE source = 'edital' AND source_id = CAST(OLD.id AS TEXT);
        END
    """)
    # Questões: INSERT
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_questoes_fts_insert AFTER INSERT ON questoes
        BEGIN
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('questao', CAST(NEW.id AS TEXT), NEW.materia, NEW.enunciado);
        END
    """)
    # Questões: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_questoes_fts_update AFTER UPDATE OF materia, enunciado ON questoes
        BEGIN
            DELETE FROM search_index WHERE source = 'questao' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('questao', CAST(NEW.id AS TEXT), NEW.materia, NEW.enunciado);
        END
    """)
    # Questões: DELETE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_questoes_fts_delete AFTER DELETE ON questoes
        BEGIN
            DELETE FROM search_index WHERE source = 'questao' AND source_id = CAST(OLD.id AS TEXT);
        END
    """)
    # Flashcards: INSERT
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_flashcards_fts_insert AFTER INSERT ON flashcards
        BEGIN
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('flashcard', CAST(NEW.id AS TEXT), NEW.pergunta, NEW.resposta);
        END
    """)
    # Flashcards: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_flashcards_fts_update AFTER UPDATE OF pergunta, resposta ON flashcards
        BEGIN
            DELETE FROM search_index WHERE source = 'flashcard' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('flashcard', CAST(NEW.id AS TEXT), NEW.pergunta, NEW.resposta);
        END
    """)
    # Flashcards: DELETE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_flashcards_fts_delete AFTER DELETE ON flashcards
        BEGIN
            DELETE FROM search_index WHERE source = 'flashcard' AND source_id = CAST(OLD.id AS TEXT);
        END
    """)
    # Notas PDF: INSERT
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_notas_fts_insert AFTER INSERT ON notas_pdf
        BEGIN
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('nota', CAST(NEW.id AS TEXT), '', NEW.conteudo);
        END
    """)
    # Notas PDF: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_notas_fts_update AFTER UPDATE OF conteudo ON notas_pdf
        BEGIN
            DELETE FROM search_index WHERE source = 'nota' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content)
            VALUES ('nota', CAST(NEW.id AS TEXT), '', NEW.conteudo);
        END
    """)
    # Notas PDF: DELETE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_notas_fts_delete AFTER DELETE ON notas_pdf
        BEGIN
            DELETE FROM search_index WHERE source = 'nota' AND source_id = CAST(OLD.id AS TEXT);
        END
    """)
    conn.commit()
    log.info("FTS5 real-time triggers created")


def init_db():
    """Inicializa o banco de dados: tabelas, migrações, índices e dados padrão."""
    conn = sqlite3.connect(DB_PATH)
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

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

def _m44_questoes_prova_origem(conn):
    """Add prova_origem column to questoes."""
    try:
        conn.execute("SELECT prova_origem FROM questoes LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE questoes ADD COLUMN prova_origem TEXT DEFAULT ''")
        log.info("Migration: added column prova_origem to questoes")

def _m45_edital_video_link(conn):
    """Add video_link column to edital for YouTube videos."""
    try:
        conn.execute("SELECT video_link FROM edital LIMIT 1")
    except Exception:
        conn.execute("ALTER TABLE edital ADD COLUMN video_link TEXT DEFAULT ''")
        log.info("Migration: added column video_link to edital")


def _m46_error_analysis(conn):
    """Create error_analysis table for categorizing why user got questions wrong."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS error_analysis (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            resposta_id INTEGER NOT NULL,
            motivo TEXT NOT NULL,
            detalhe TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (resposta_id) REFERENCES questoes_respostas(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_analysis_user_id ON error_analysis(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_error_analysis_motivo ON error_analysis(motivo, user_id)")
    log.info("Migration: created error_analysis table")


def _m47_topic_dependencies(conn):
    """Create topic_dependencies table for knowledge graph."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS topic_dependencies (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL,
            depends_on_id INTEGER NOT NULL,
            relationship TEXT NOT NULL DEFAULT 'prerequisite',
            user_id INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (topic_id) REFERENCES edital(id),
            FOREIGN KEY (depends_on_id) REFERENCES edital(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_topic_deps_topic ON topic_dependencies(topic_id, user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_topic_deps_depends ON topic_dependencies(depends_on_id, user_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_topic_deps_unique ON topic_dependencies(topic_id, depends_on_id, user_id)")
    log.info("Migration: created topic_dependencies table")


def _m48_brain_dump_log(conn):
    """Create brain_dump_log table for Free Recall technique."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS brain_dump_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            materia TEXT NOT NULL,
            topico TEXT DEFAULT '',
            texto TEXT NOT NULL,
            palavras INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_brain_dump_user ON brain_dump_log(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_brain_dump_materia ON brain_dump_log(user_id, materia)")
    log.info("Migration: created brain_dump_log table")


def _m49_questoes_texto_base(conn):
    """Add texto_base column to questoes for questions that share a base text."""
    try:
        conn.execute("ALTER TABLE questoes ADD COLUMN texto_base TEXT DEFAULT ''")
        log.info("Migration: added texto_base column to questoes")
    except Exception:
        pass  # Column already exists


def _m50_creditos_users(conn):
    """Add credit system columns to users table."""
    try:
        conn.execute("ALTER TABLE users ADD COLUMN creditos_saldo INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE users ADD COLUMN creditos_expira TEXT DEFAULT ''")
    except Exception:
        pass
    # Tabela de histórico de créditos (compras, consumos)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS creditos_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            saldo_anterior INTEGER NOT NULL DEFAULT 0,
            saldo_posterior INTEGER NOT NULL DEFAULT 0,
            motivo TEXT DEFAULT '',
            expira TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_creditos_hist_user ON creditos_historico(user_id)")
    log.info("Migration: added credit system (creditos_saldo, creditos_historico)")


def _m51_pagamentos(conn):
    """Create pagamentos table for payment tracking."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pagamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            payment_id TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'pix_creditos',
            creditos INTEGER DEFAULT 0,
            valor REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pagamentos_user ON pagamentos(user_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pagamentos_payment_id ON pagamentos(payment_id)")
    log.info("Migration: created pagamentos table")


def _m52_pdf_organizacao_virtual(conn):
    """Create virtual folder organization for PDFs (per user)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_pastas_virtuais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            nome TEXT NOT NULL,
            parent_id INTEGER DEFAULT NULL,
            posicao INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES pdf_pastas_virtuais(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pdf_pastas_user ON pdf_pastas_virtuais(user_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_organizacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            pdf_path TEXT NOT NULL,
            pasta_virtual_id INTEGER DEFAULT NULL,
            posicao INTEGER DEFAULT 0,
            FOREIGN KEY (pasta_virtual_id) REFERENCES pdf_pastas_virtuais(id)
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pdf_org_user_path ON pdf_organizacao(user_id, pdf_path)")
    log.info("Migration: created pdf_pastas_virtuais + pdf_organizacao tables")


def _m53_cadernos_questoes(conn):
    """Upgrade cadernos table and create cadernos_questoes for question notebooks."""
    # Adicionar colunas novas à tabela cadernos existente
    for col, defn in [("user_id", "INTEGER NOT NULL DEFAULT 1"), ("cor", "TEXT DEFAULT '#89b4fa'"), ("updated_at", "TEXT DEFAULT ''")]:
        try:
            conn.execute(f"ALTER TABLE cadernos ADD COLUMN {col} {defn}")
        except Exception:
            pass  # Coluna já existe

    conn.execute("CREATE INDEX IF NOT EXISTS idx_cadernos_user ON cadernos(user_id)")

    # Nova tabela de associação cadernos ↔ questões
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cadernos_questoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caderno_id INTEGER NOT NULL,
            questao_id INTEGER NOT NULL,
            ordem INTEGER DEFAULT 0,
            added_at TEXT NOT NULL,
            FOREIGN KEY (caderno_id) REFERENCES cadernos(id) ON DELETE CASCADE,
            FOREIGN KEY (questao_id) REFERENCES questoes(id)
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_cadernos_questoes_unique ON cadernos_questoes(caderno_id, questao_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cadernos_questoes_caderno ON cadernos_questoes(caderno_id)")
    log.info("Migration: upgraded cadernos + created cadernos_questoes table")


def _m54_app_config(conn):
    """Create app_config table for dynamic runtime configuration (editable by admin)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS app_config (
            chave TEXT PRIMARY KEY,
            valor TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        )
    """)
    log.info("Migration: created app_config table")


def _m55_user_status(conn):
    """Create user_status table for social presence (o que cada usuário está fazendo)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_status (
            user_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'offline',
            materia TEXT DEFAULT '',
            detalhe TEXT DEFAULT '',
            atualizado_em TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_status_atualizado ON user_status(atualizado_em)")
    log.info("Migration: created user_status table")


def _m56_catalogo_itens(conn):
    """Create catalogo_itens table for the public materials catalog.

    Cada item aponta para um recurso na conta de um curador (origem_uid).
    Estudantes importam → copia da conta do curador para a deles.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS catalogo_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL,
            titulo TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            categoria TEXT DEFAULT 'Geral',
            curador_uid INTEGER NOT NULL,
            origem_uid INTEGER NOT NULL,
            ref TEXT DEFAULT '',
            downloads INTEGER DEFAULT 0,
            ativo INTEGER DEFAULT 1,
            publicado_em TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalogo_ativo ON catalogo_itens(ativo, categoria)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalogo_tipo ON catalogo_itens(tipo)")
    log.info("Migration: created catalogo_itens table")


def _m57_catalogo_reputacao(conn):
    """Avaliações (estrelas) nos materiais + selo verificado + moderação.

    - catalogo_avaliacoes: nota 1-5 + comentário por usuário/item (upsert).
    - users.curador_verificado: selo de curador confiável (admin concede).
    - catalogo_itens.status: 'aprovado' (default) ou 'pendente' (premium não-verificado).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS catalogo_avaliacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nota INTEGER NOT NULL,
            comentario TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_catalogo_aval_unique ON catalogo_avaliacoes(item_id, user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_catalogo_aval_item ON catalogo_avaliacoes(item_id)")

    # Selo de curador verificado
    try:
        conn.execute("ALTER TABLE users ADD COLUMN curador_verificado INTEGER DEFAULT 0")
    except Exception:
        pass

    # Status de moderação do item do catálogo
    try:
        conn.execute("ALTER TABLE catalogo_itens ADD COLUMN status TEXT DEFAULT 'aprovado'")
    except Exception:
        pass

    log.info("Migration: created catalogo_avaliacoes + curador_verificado + item status")


def _m58_trilha(conn):
    """Trilha de estudo (roadmap): sequência ordenada de etapas por tópico do edital.

    - trilha: cabeçalho (uma trilha ativa por edital/usuário).
    - trilha_etapas: etapas ordenadas, cada uma referenciando um tópico do edital,
      com estado de progresso longitudinal (bloqueada/atual/concluída) e o
      pré-requisito (etapa anterior na ordem topológica do knowledge graph).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trilha (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            nome TEXT NOT NULL DEFAULT 'Minha Trilha',
            edital_nome TEXT DEFAULT '',
            cargo TEXT DEFAULT '',
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trilha_etapas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trilha_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL DEFAULT 1,
            ordem INTEGER NOT NULL DEFAULT 0,
            topico_id INTEGER,
            materia TEXT NOT NULL DEFAULT '',
            topico TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'bloqueada',
            desbloqueada INTEGER NOT NULL DEFAULT 0,
            prerequisito_etapa_id INTEGER,
            razao TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (trilha_id) REFERENCES trilha(id),
            FOREIGN KEY (topico_id) REFERENCES edital(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trilha_user ON trilha(user_id, ativo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trilha_etapas_trilha ON trilha_etapas(trilha_id, ordem)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trilha_etapas_user ON trilha_etapas(user_id)")
    log.info("Migration: created trilha + trilha_etapas tables")


def _m59_metas_cargo_alvo(conn):
    """Cargo/edital alvo do usuário — usado pela trilha e demais features focadas
    num único cargo, evitando agregar tópicos de todos os cargos do concurso."""
    for col in ("edital_alvo", "cargo_alvo"):
        try:
            conn.execute(f"ALTER TABLE metas_config ADD COLUMN {col} TEXT DEFAULT ''")
        except Exception:
            pass  # coluna já existe
    log.info("Migration: added edital_alvo/cargo_alvo to metas_config")


def _m60_simulados_tempo_registrado(conn):
    """Rastreia quanto tempo do simulado já virou sessão de estudo, para permitir
    registro incremental (heartbeat) e de simulados abandonados sem dupla contagem."""
    try:
        conn.execute("ALTER TABLE simulados ADD COLUMN tempo_registrado_seg INTEGER DEFAULT 0")
    except Exception:
        pass  # coluna já existe
    log.info("Migration: added tempo_registrado_seg to simulados")


def _m61_metas_semanais_manuais(conn):
    """Override manual da Meta da Semana. Valor 0 = usar cálculo automático
    (derivado do desempenho). > 0 = valor fixo definido pelo usuário."""
    for col in ("meta_semanal_horas", "meta_semanal_questoes", "meta_semanal_flashcards"):
        try:
            default = "0.0" if col == "meta_semanal_horas" else "0"
            tipo = "REAL" if col == "meta_semanal_horas" else "INTEGER"
            conn.execute(f"ALTER TABLE metas_config ADD COLUMN {col} {tipo} DEFAULT {default}")
        except Exception:
            pass  # coluna já existe
    log.info("Migration: added meta_semanal_horas/questoes/flashcards to metas_config")


def _m62_revisao_oclusoes(conn):
    """Occlusão de imagem (image occlusion) nos recortes do caderno de revisão.

    Armazena um JSON com a lista de retângulos ocultos, cada um em coordenadas
    relativas (0-1) à imagem: [{"x":0.1,"y":0.2,"w":0.3,"h":0.05}, ...].
    Vazio/'' = sem oclusões (comportamento anterior)."""
    try:
        conn.execute("ALTER TABLE revisao_blocos ADD COLUMN oclusoes TEXT DEFAULT ''")
        log.info("Migration: added oclusoes column to revisao_blocos")
    except Exception:
        pass  # coluna já existe


def _m63_revisao_agenda(conn):
    """Agendamento espaçado do caderno de revisão (Spaced Practice no nível do
    caderno = pdf_path). Cada linha guarda quando o caderno de um PDF deve ser
    revisado novamente e o intervalo atual (expande a cada revisão concluída)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS revisao_agenda (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            pdf_path TEXT NOT NULL,
            proxima_revisao TEXT NOT NULL,
            intervalo_dias INTEGER NOT NULL DEFAULT 1,
            revisoes_count INTEGER NOT NULL DEFAULT 0,
            ultima_revisao TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_revisao_agenda_user_pdf ON revisao_agenda(user_id, pdf_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_revisao_agenda_proxima ON revisao_agenda(user_id, proxima_revisao)")
    log.info("Migration: created revisao_agenda table")


def _m64_revisao_tag(conn):
    """Tag/categoria por bloco de revisão (decorar/entender/pegadinha/revisar),
    usada para colorir e filtrar os blocos. Vazio = sem tag."""
    try:
        conn.execute("ALTER TABLE revisao_blocos ADD COLUMN tag TEXT DEFAULT ''")
        log.info("Migration: added tag column to revisao_blocos")
    except Exception:
        pass  # coluna já existe


def _m65_destaques_pdf(conn):
    """Camada própria de destaques (marca-texto) persistentes por página do PDF.

    rects: JSON com os retângulos da seleção em coords relativas 0-1 à página
    (uma seleção de texto pode gerar vários retângulos, ex: várias linhas).
    texto: o trecho destacado (para listar/buscar/exportar)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS destaques_pdf (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            pdf_path TEXT NOT NULL,
            pagina INTEGER NOT NULL DEFAULT 1,
            cor TEXT NOT NULL DEFAULT 'yellow',
            texto TEXT DEFAULT '',
            rects TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_destaques_user_pdf ON destaques_pdf(user_id, pdf_path)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_destaques_user_pdf_pag ON destaques_pdf(user_id, pdf_path, pagina)")
    log.info("Migration: created destaques_pdf table")


def _m66_destaques_estilo(conn):
    """Estilo de marcação do destaque: highlight (marca-texto), underline
    (sublinhado), strike (tachado), box (contorno). Default highlight."""
    try:
        conn.execute("ALTER TABLE destaques_pdf ADD COLUMN estilo TEXT DEFAULT 'highlight'")
        log.info("Migration: added estilo column to destaques_pdf")
    except Exception:
        pass  # coluna já existe


def _m67_destaques_comentario(conn):
    """Comentário/nota anexado a um destaque (Elaborative Interrogation)."""
    try:
        conn.execute("ALTER TABLE destaques_pdf ADD COLUMN comentario TEXT DEFAULT ''")
        log.info("Migration: added comentario column to destaques_pdf")
    except Exception:
        pass  # coluna já existe


def _m68_pdf_ownership(conn):
    """Visibilidade de PDFs por usuário: dono + compartilhamento self-service.

    Os arquivos permanecem globais no disco (PDF_ROOT). O controle de acesso é
    feito na camada de metadados:
      - pdf_owner: quem é o dono de cada pdf_path (backfill → uid 1).
      - pdf_compartilhamentos: donos concedem acesso de leitura a outros usuários.

    Também corrige a PK da tabela progress: era apenas (path), o que impedia dois
    usuários de ter progresso independente no mesmo arquivo. Passa a ser
    (path, user_id), preservando todos os dados existentes.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()

    # ---- 1. Tabela de donos ----
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_owner (
            pdf_path TEXT PRIMARY KEY,
            owner_id INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pdf_owner_owner ON pdf_owner(owner_id)")

    # ---- 2. Tabela de compartilhamentos ----
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pdf_compartilhamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_path TEXT NOT NULL,
            owner_id INTEGER NOT NULL,
            shared_with_id INTEGER NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_pdf_compart_unique ON pdf_compartilhamentos(pdf_path, shared_with_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pdf_compart_shared ON pdf_compartilhamentos(shared_with_id)"
    )

    # ---- 3. Backfill: todos os PDFs existentes pertencem ao uid 1 ----
    # (a) paths já registrados em progress
    try:
        paths = {r[0] for r in conn.execute("SELECT DISTINCT path FROM progress").fetchall()}
    except Exception:
        paths = set()

    # (b) paths presentes no disco (PDF_ROOT), via build_tree
    try:
        from settings import settings
        from utils import build_tree
        from pathlib import Path as _Path

        root = settings.PDF_ROOT
        if root and _Path(root).exists():
            def _collect(nodes):
                for n in nodes:
                    if n.get("type") == "pdf" and n.get("path"):
                        paths.add(n["path"])
                    elif n.get("type") == "folder":
                        _collect(n.get("children", []))
            _collect(build_tree(root))
    except Exception as e:
        log.warning(f"Migration 68: não foi possível varrer PDF_ROOT no backfill: {e}")

    for p in paths:
        conn.execute(
            "INSERT OR IGNORE INTO pdf_owner (pdf_path, owner_id, created_at) VALUES (?, 1, ?)",
            (p, now)
        )
    log.info(f"Migration 68: {len(paths)} PDF(s) atribuídos ao dono uid=1")

    # ---- 4. Corrigir PK de progress: (path) -> (path, user_id) ----
    table_info = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='progress'"
    ).fetchone()
    sql = (table_info[0] if table_info else "") or ""
    # Só recria se a PK ainda for apenas (path) — isto é, não contém PRIMARY KEY composta
    if "PRIMARY KEY (path, user_id)" not in sql and "PRIMARY KEY(path, user_id)" not in sql:
        try:
            # Descobrir colunas existentes para copiar de forma robusta
            cols = [r[1] for r in conn.execute("PRAGMA table_info(progress)").fetchall()]
            has_last_read = "last_read_at" in cols

            conn.execute("ALTER TABLE progress RENAME TO _progress_old")
            conn.execute("""
                CREATE TABLE progress (
                    path TEXT NOT NULL,
                    current_page INTEGER DEFAULT 1,
                    total_pages INTEGER DEFAULT 1,
                    user_id INTEGER NOT NULL DEFAULT 1,
                    last_read_at TEXT DEFAULT '',
                    PRIMARY KEY (path, user_id)
                )
            """)
            if has_last_read:
                conn.execute("""
                    INSERT INTO progress (path, current_page, total_pages, user_id, last_read_at)
                    SELECT path, current_page, total_pages, COALESCE(user_id, 1),
                           COALESCE(last_read_at, '')
                    FROM _progress_old
                """)
            else:
                conn.execute("""
                    INSERT INTO progress (path, current_page, total_pages, user_id, last_read_at)
                    SELECT path, current_page, total_pages, COALESCE(user_id, 1), ''
                    FROM _progress_old
                """)
            conn.execute("DROP TABLE _progress_old")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_progress_user_id ON progress(user_id)")
            log.info("Migration 68: progress PK corrigida para (path, user_id)")
        except Exception as e:
            log.warning(f"Migration 68: falha ao recriar progress: {e}")


def _m69_admin_audit(conn):
    """Log de auditoria de ações administrativas.

    Registra quem (admin_id) fez qual ação (acao) sobre qual alvo (alvo_tipo/
    alvo_id), com detalhe livre (JSON ou texto) e timestamp. Usado para
    rastreabilidade de ações sensíveis (alterar plano, créditos, excluir
    usuário, definir dono de PDF, publicar no catálogo, etc.).
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            acao TEXT NOT NULL,
            alvo_tipo TEXT DEFAULT '',
            alvo_id TEXT DEFAULT '',
            detalhe TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit(created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_admin ON admin_audit(admin_id, created_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_admin_audit_acao ON admin_audit(acao, created_at DESC)")
    log.info("Migration: created admin_audit table")


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
    (44, _m44_questoes_prova_origem),
    (45, _m45_edital_video_link),
    (46, _m46_error_analysis),
    (47, _m47_topic_dependencies),
    (48, _m48_brain_dump_log),
    (49, _m49_questoes_texto_base),
    (50, _m50_creditos_users),
    (51, _m51_pagamentos),
    (52, _m52_pdf_organizacao_virtual),
    (53, _m53_cadernos_questoes),
    (54, _m54_app_config),
    (55, _m55_user_status),
    (56, _m56_catalogo_itens),
    (57, _m57_catalogo_reputacao),
    (58, _m58_trilha),
    (59, _m59_metas_cargo_alvo),
    (60, _m60_simulados_tempo_registrado),
    (61, _m61_metas_semanais_manuais),
    (62, _m62_revisao_oclusoes),
    (63, _m63_revisao_agenda),
    (64, _m64_revisao_tag),
    (65, _m65_destaques_pdf),
    (66, _m66_destaques_estilo),
    (67, _m67_destaques_comentario),
    (68, _m68_pdf_ownership),
    (69, _m69_admin_audit),
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

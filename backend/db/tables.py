"""Criação de todas as tabelas do sistema."""


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
            confianca INTEGER DEFAULT NULL,
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
            data TEXT NOT NULL,
            horas_estudadas REAL DEFAULT 0.0,
            questoes_resolvidas INTEGER DEFAULT 0,
            flashcards_revisados INTEGER DEFAULT 0,
            user_id INTEGER NOT NULL DEFAULT 1,
            UNIQUE(user_id, data)
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

    # Cadernos de Questões
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cadernos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            nome TEXT NOT NULL,
            descricao TEXT DEFAULT '',
            cor TEXT DEFAULT '#89b4fa',
            created_at TEXT NOT NULL,
            updated_at TEXT DEFAULT ''
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cadernos_user ON cadernos(user_id)")

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

    # Manter caderno_itens para backward compatibility
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

    # Caderno de Revisão por PDF — blocos capturados do PDF original
    # (Distributed Summary + Dual Coding + Cognitive Load Segmenting)
    # tipo: 'recorte' (imagem da página) | 'resumo_ia' | 'texto' | 'nota'
    conn.execute("""
        CREATE TABLE IF NOT EXISTS revisao_blocos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            pdf_path TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'recorte',
            titulo TEXT DEFAULT '',
            conteudo TEXT DEFAULT '',
            imagem_data TEXT DEFAULT '',
            pagina INTEGER DEFAULT 1,
            ordem INTEGER DEFAULT 0,
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

    # ========== TRILHA (roadmap de estudo por tópicos) ==========
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trilha (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL DEFAULT 1,
            nome TEXT NOT NULL DEFAULT 'Minha Trilha',
            edital_nome TEXT DEFAULT '',
            cargo TEXT DEFAULT '',
            ativo INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
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
            created_at TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (trilha_id) REFERENCES trilha(id),
            FOREIGN KEY (topico_id) REFERENCES edital(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trilha_user ON trilha(user_id, ativo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trilha_etapas_trilha ON trilha_etapas(trilha_id, ordem)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trilha_etapas_user ON trilha_etapas(user_id)")

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

    # ========== ELABORATION LOG (A3) ==========
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

    # ========== SESSION METRICS (Fatigue Detection B3) ==========
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

    # Generation Mode (Active Recall sem alternativas)
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

    # ========== SESSÃO ADAPTATIVA / CAT (C1) ==========
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

    # ========== BRAIN DUMP LOG (Free Recall technique) ==========
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

    # ========== SCHEMA VERSION (versionamento de migrations) ==========
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """)

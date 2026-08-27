"""Criação de índices para performance e FTS5."""


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

    # FTS5 Full-Text Search (with user_id for isolation)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS search_index USING fts5(
            source,
            source_id,
            title,
            content,
            user_id UNINDEXED,
            tokenize='unicode61'
        )
    """)

    # Índices em user_id para isolamento multi-tenant
    conn.execute("CREATE INDEX IF NOT EXISTS idx_streaks_user_id ON streaks(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sessoes_user_id ON sessoes_estudo(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_questoes_respostas_user_id ON questoes_respostas(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edital_user_id ON edital(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_user_id ON flashcards(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sumulas_user_id ON sumulas(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ciclo_user_id ON ciclo_estudos(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_simulados_user_id ON simulados(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notas_pdf_user_id ON notas_pdf(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_bookmarks_pdf_user_id ON bookmarks_pdf(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cadernos_user_id ON cadernos(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_feynman_user_id ON feynman(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_calendario_atividades_user_id ON calendario_atividades(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_desafios_user_id ON desafios(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ai_conversations_user_id ON ai_conversations(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_notas_topico_user_id ON notas_topico(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_planejador_user_id ON planejador_semanal(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_user_gamification_user_id ON user_gamification(user_id)")

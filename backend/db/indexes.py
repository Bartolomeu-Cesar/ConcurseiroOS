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

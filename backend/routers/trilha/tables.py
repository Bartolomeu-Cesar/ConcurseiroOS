"""Garantia de schema para a Trilha (compat com DBs sem a migration #58)."""


def _ensure_tables(conn):
    """Cria as tabelas da trilha se não existirem (idempotente).

    Espelha a migration #58. Chamado no início de cada endpoint, seguindo o
    mesmo padrão defensivo do knowledge_graph._ensure_table.
    """
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

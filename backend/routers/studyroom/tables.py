"""DDL e migrations do módulo Study Room — chamado uma vez no startup."""


def ensure_studyroom_tables(conn):
    """Cria tabelas de study room se não existirem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_rooms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT UNIQUE NOT NULL,
            criador_id INTEGER NOT NULL,
            titulo TEXT DEFAULT 'Sala de Estudos',
            max_participantes INTEGER DEFAULT 10,
            tecnica TEXT DEFAULT 'pomodoro',
            duracao_min INTEGER DEFAULT 50,
            status TEXT DEFAULT 'ativa',
            ciclo_foco_min INTEGER DEFAULT 25,
            ciclo_pausa_min INTEGER DEFAULT 5,
            ciclos_total INTEGER DEFAULT 4,
            pausa_longa_min INTEGER DEFAULT 15,
            modo_foco INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT 'Estudante',
            status TEXT DEFAULT 'focando',
            tempo_estudado_seg INTEGER DEFAULT 0,
            ultimo_checkin TEXT DEFAULT '',
            meta TEXT DEFAULT '',
            joined_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_chat (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT 'Estudante',
            mensagem TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_todos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            texto TEXT NOT NULL,
            completo INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_rooms_codigo ON study_rooms(codigo)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_participants_room ON study_room_participants(room_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_chat_room ON study_room_chat(room_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_study_room_todos_room ON study_room_todos(room_id)")
    conn.commit()


def run_studyroom_migrations(conn):
    """Adiciona colunas novas às tabelas existentes (idempotente)."""
    migrations = [
        ("study_room_participants", "meta", "ALTER TABLE study_room_participants ADD COLUMN meta TEXT DEFAULT ''"),
        ("study_rooms", "ciclo_foco_min", "ALTER TABLE study_rooms ADD COLUMN ciclo_foco_min INTEGER DEFAULT 25"),
        ("study_rooms", "ciclo_pausa_min", "ALTER TABLE study_rooms ADD COLUMN ciclo_pausa_min INTEGER DEFAULT 5"),
        ("study_rooms", "ciclos_total", "ALTER TABLE study_rooms ADD COLUMN ciclos_total INTEGER DEFAULT 4"),
        ("study_rooms", "pausa_longa_min", "ALTER TABLE study_rooms ADD COLUMN pausa_longa_min INTEGER DEFAULT 15"),
        ("study_rooms", "modo_foco", "ALTER TABLE study_rooms ADD COLUMN modo_foco INTEGER DEFAULT 0"),
    ]
    for _table, _col, sql in migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            pass  # Column already exists


def ensure_commitment_tables(conn):
    """Cria tabela de commitments se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_commitments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT '',
            commitment TEXT NOT NULL,
            xp_stake INTEGER DEFAULT 50,
            cumprida INTEGER DEFAULT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def ensure_intention_tables(conn):
    """Cria tabela de intentions se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_intentions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            intencao TEXT NOT NULL,
            como_vou_estudar TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def ensure_reflection_tables(conn):
    """Cria tabela de reflections se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_reflections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            o_que_aprendi TEXT NOT NULL,
            o_que_foi_dificil TEXT NOT NULL,
            proximo_passo TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def ensure_challenge_tables(conn):
    """Cria tabela de challenges se não existir."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_challenges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            materia TEXT NOT NULL,
            quantidade INTEGER NOT NULL,
            tempo_limite_min INTEGER DEFAULT 15,
            boss_hp_atual INTEGER NOT NULL,
            status TEXT DEFAULT 'ativo',
            questoes_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.commit()


def ensure_discussion_tables(conn):
    """Cria tabelas de discussions se não existirem."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_discussions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            questao_id INTEGER,
            enunciado TEXT NOT NULL,
            alternativas_json TEXT,
            resposta_correta TEXT,
            materia TEXT DEFAULT '',
            status TEXT DEFAULT 'aberta',
            created_at TEXT NOT NULL,
            FOREIGN KEY (room_id) REFERENCES study_rooms(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_discussion_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT '',
            resposta TEXT NOT NULL,
            justificativa TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (discussion_id) REFERENCES study_room_discussions(id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS study_room_discussion_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discussion_id INTEGER NOT NULL,
            response_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            nome TEXT DEFAULT '',
            comentario TEXT NOT NULL,
            concordo INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (discussion_id) REFERENCES study_room_discussions(id),
            FOREIGN KEY (response_id) REFERENCES study_room_discussion_responses(id)
        )
    """)
    conn.commit()


def ensure_all_tables(conn):
    """Garante que todas as tabelas do módulo existem. Chamado uma vez no startup."""
    ensure_studyroom_tables(conn)
    run_studyroom_migrations(conn)
    ensure_commitment_tables(conn)
    ensure_intention_tables(conn)
    ensure_reflection_tables(conn)
    ensure_challenge_tables(conn)
    ensure_discussion_tables(conn)

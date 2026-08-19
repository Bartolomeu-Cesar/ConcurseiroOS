import sqlite3
from collections.abc import Generator
from contextlib import contextmanager

from logger import log
from settings import settings

DB_PATH = settings.DB_PATH


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_db_session() -> Generator[sqlite3.Connection, None, None]:
    """FastAPI dependency que fornece uma conexão ao banco de dados."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
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


def init_db():
    """Inicializa o banco de dados: tabelas, migrações, índices e dados padrão."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    _create_tables(conn)
    _run_migrations(conn)
    _create_indexes(conn)
    _seed_defaults(conn)
    conn.commit()
    rebuild_search_index(conn)
    conn.close()
    log.info("Database initialized")

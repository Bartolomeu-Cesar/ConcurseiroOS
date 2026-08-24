"""Índice de busca FTS5 e triggers em tempo real."""
from logger import log


def rebuild_search_index(conn):
    """Reconstrói o índice FTS5 com todos os dados (incluindo user_id para filtragem)."""
    conn.execute("DELETE FROM search_index")

    # Tópicos do edital
    rows = conn.execute("SELECT id, materia, topico, user_id FROM edital").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content, user_id) VALUES (?, ?, ?, ?, ?)",
            ("edital", str(r[0]), r[1], r[2], r[3] or 1)
        )

    # Questões
    rows = conn.execute("SELECT id, materia, enunciado, user_id FROM questoes").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content, user_id) VALUES (?, ?, ?, ?, ?)",
            ("questao", str(r[0]), r[1], r[2], r[3] or 1)
        )

    # Flashcards
    rows = conn.execute("SELECT id, pergunta, resposta, user_id FROM flashcards").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content, user_id) VALUES (?, ?, ?, ?, ?)",
            ("flashcard", str(r[0]), r[1], r[2], r[3] or 1)
        )

    # Notas
    rows = conn.execute("SELECT id, conteudo, user_id FROM notas_pdf").fetchall()
    for r in rows:
        conn.execute(
            "INSERT INTO search_index (source, source_id, title, content, user_id) VALUES (?, ?, ?, ?, ?)",
            ("nota", str(r[0]), "", r[1], r[2] or 1)
        )

    conn.commit()
    log.info("Search index rebuilt (with user_id)")


def _create_fts5_triggers(conn):
    """Cria triggers para manter o índice FTS5 atualizado em tempo real (com user_id)."""
    # Edital: INSERT
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_edital_fts_insert AFTER INSERT ON edital
        BEGIN
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('edital', CAST(NEW.id AS TEXT), NEW.materia, NEW.topico, COALESCE(NEW.user_id, 1));
        END
    """)
    # Edital: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_edital_fts_update AFTER UPDATE OF materia, topico ON edital
        BEGIN
            DELETE FROM search_index WHERE source = 'edital' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('edital', CAST(NEW.id AS TEXT), NEW.materia, NEW.topico, COALESCE(NEW.user_id, 1));
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
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('questao', CAST(NEW.id AS TEXT), NEW.materia, NEW.enunciado, COALESCE(NEW.user_id, 1));
        END
    """)
    # Questões: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_questoes_fts_update AFTER UPDATE OF materia, enunciado ON questoes
        BEGIN
            DELETE FROM search_index WHERE source = 'questao' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('questao', CAST(NEW.id AS TEXT), NEW.materia, NEW.enunciado, COALESCE(NEW.user_id, 1));
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
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('flashcard', CAST(NEW.id AS TEXT), NEW.pergunta, NEW.resposta, COALESCE(NEW.user_id, 1));
        END
    """)
    # Flashcards: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_flashcards_fts_update AFTER UPDATE OF pergunta, resposta ON flashcards
        BEGIN
            DELETE FROM search_index WHERE source = 'flashcard' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('flashcard', CAST(NEW.id AS TEXT), NEW.pergunta, NEW.resposta, COALESCE(NEW.user_id, 1));
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
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('nota', CAST(NEW.id AS TEXT), '', NEW.conteudo, COALESCE(NEW.user_id, 1));
        END
    """)
    # Notas PDF: UPDATE
    conn.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_notas_fts_update AFTER UPDATE OF conteudo ON notas_pdf
        BEGIN
            DELETE FROM search_index WHERE source = 'nota' AND source_id = CAST(OLD.id AS TEXT);
            INSERT INTO search_index (source, source_id, title, content, user_id)
            VALUES ('nota', CAST(NEW.id AS TEXT), '', NEW.conteudo, COALESCE(NEW.user_id, 1));
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
    log.info("FTS5 real-time triggers created (with user_id)")

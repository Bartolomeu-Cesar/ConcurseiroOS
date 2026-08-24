"""Dados padrão (seeds) para o banco de dados."""
from logger import log


def _seed_defaults(conn):
    """Insere dados padrão se não existirem."""
    conn.execute("""
        INSERT OR IGNORE INTO metas_config (id, meta_horas, meta_questoes, meta_flashcards, meta_paginas)
        VALUES (1, 3.0, 30, 10, 20)
    """)

    # Garantir que user_id=1 existe na tabela users (modo guest)
    user_exists = conn.execute("SELECT id FROM users WHERE id = 1").fetchone()
    if not user_exists:
        conn.execute("""
            INSERT OR IGNORE INTO users (id, email, nome, username, plano, created_at)
            VALUES (1, 'admin@concurseiroos.app', 'Bartholomew Caesar', 'Bartholomew', 'ilimitado', datetime('now'))
        """)
        log.info("Seed: created default user (id=1, Bartholomew Caesar)")
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

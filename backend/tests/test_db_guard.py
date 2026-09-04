"""Testes do db_guard — detecção de diff espúrio vs. dado real no progress.db.

Cobre a lógica de decisão sem depender de git: monta bancos SQLite temporários
(base e atual) e valida _snapshot + diff_snapshots + classificação de efêmeras.

Executar: pytest tests/test_db_guard.py -v
"""

import os
import sqlite3
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db_guard


def _mk_db(
    path,
    *,
    flashcards=0,
    user_status_val="offline",
    search_rows=0,
    schema_ver=1,
    bot_xp=100,
    real_xp=50,
    last_login="2026-01-01T00:00:00",
    user_nome="Estudante",
):
    """Cria um .db com tabelas reais (flashcards) e efêmeras (user_status,
    search_index, schema_version) para simular os diffs do dia a dia.

    Inclui league_members com um BOT (user_id<0, XP simulado) e o usuário REAL
    (user_id>0) para exercitar o filtro de bots do db_guard, e users com
    last_login (coluna efêmera) + nome (dado real) para o filtro de colunas."""
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE flashcards (id INTEGER PRIMARY KEY, pergunta TEXT, resposta TEXT)")
    c.execute("CREATE TABLE user_status (user_id INTEGER PRIMARY KEY, status TEXT, atualizado_em TEXT)")
    c.execute("CREATE TABLE search_index (rowid INTEGER PRIMARY KEY, texto TEXT)")
    c.execute("CREATE TABLE schema_version (version INTEGER)")
    c.execute("CREATE TABLE league_members (id INTEGER PRIMARY KEY, user_id INTEGER, weekly_xp INTEGER)")
    c.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, nome TEXT, last_login TEXT)")
    for i in range(flashcards):
        c.execute("INSERT INTO flashcards (pergunta, resposta) VALUES (?, ?)", (f"p{i}", f"r{i}"))
    c.execute("INSERT INTO user_status VALUES (1, ?, '2026-01-01T00:00:00')", (user_status_val,))
    for i in range(search_rows):
        c.execute("INSERT INTO search_index (texto) VALUES (?)", (f"t{i}",))
    c.execute("INSERT INTO schema_version VALUES (?)", (schema_ver,))
    c.execute("INSERT INTO league_members VALUES (1, -1, ?)", (bot_xp,))  # bot simulado
    c.execute("INSERT INTO league_members VALUES (2, 1, ?)", (real_xp,))  # usuário real
    c.execute("INSERT INTO users VALUES (1, ?, ?)", (user_nome, last_login))
    c.commit()
    c.close()


@pytest.fixture
def dois_dbs():
    base = tempfile.NamedTemporaryFile(suffix="_base.db", delete=False)
    atual = tempfile.NamedTemporaryFile(suffix="_atual.db", delete=False)
    base.close()
    atual.close()
    yield base.name, atual.name
    for p in (base.name, atual.name):
        try:
            os.unlink(p)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Classificação de tabelas
# ---------------------------------------------------------------------------


def test_efemeras_reconhecidas():
    assert db_guard._e_efemera("search_index")
    assert db_guard._e_efemera("search_index_data")
    assert db_guard._e_efemera("vademecum_fts_idx")
    assert db_guard._e_efemera("schema_version")
    assert db_guard._e_efemera("user_status")
    assert db_guard._e_efemera("auth_codes")


def test_tabelas_reais_nao_sao_efemeras():
    for t in ("flashcards", "questoes", "edital", "sessoes_estudo", "users", "pdf_owner"):
        assert not db_guard._e_efemera(t), f"{t} não deveria ser efêmera"


def test_snapshot_ignora_efemeras(dois_dbs):
    _, atual = dois_dbs
    _mk_db(atual, flashcards=3, search_rows=5)
    snap = db_guard._snapshot(atual)
    assert "flashcards" in snap
    assert "user_status" not in snap
    assert "search_index" not in snap
    assert "schema_version" not in snap


# ---------------------------------------------------------------------------
# Cenário ESPÚRIO: só mudaram efêmeras (presença, FTS, schema_version)
# ---------------------------------------------------------------------------


def test_diff_espurio_quando_so_efemeras_mudam(dois_dbs):
    base, atual = dois_dbs
    _mk_db(base, flashcards=5, user_status_val="estudando", search_rows=2, schema_ver=74)
    # Mesmos dados reais; muda presença, FTS e versão de schema (o que os testes fazem).
    _mk_db(atual, flashcards=5, user_status_val="offline", search_rows=9, schema_ver=75)
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "espurio", rel
    assert rel["tabelas_alteradas"] == []


# ---------------------------------------------------------------------------
# Cenário DADO REAL: tabela real mudou
# ---------------------------------------------------------------------------


def test_diff_dado_real_quando_flashcards_muda(dois_dbs):
    base, atual = dois_dbs
    _mk_db(base, flashcards=5)
    _mk_db(atual, flashcards=6)  # +1 flashcard = dado real
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "dado_real", rel
    assert "flashcards" in rel["tabelas_alteradas"]
    assert rel["detalhe"]["flashcards"]["delta"] == 1


def test_diff_dado_real_mesmo_com_contagem_igual(dois_dbs):
    """Contagem igual mas CONTEÚDO diferente ainda é dado real (hash pega)."""
    base, atual = dois_dbs
    _mk_db(base, flashcards=3)
    _mk_db(atual, flashcards=3)
    # Edita o conteúdo de um flashcard sem mudar a contagem.
    c2 = sqlite3.connect(atual)
    c2.execute("UPDATE flashcards SET resposta = 'EDITADO' WHERE id = 1")
    c2.commit()
    c2.close()
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "dado_real", rel
    assert "flashcards" in rel["tabelas_alteradas"]
    assert rel["detalhe"]["flashcards"]["delta"] == 0  # mesma contagem, conteúdo mudou


# ---------------------------------------------------------------------------
# Filtro de bots (user_id < 0): XP simulado de oponentes não é dado real
# ---------------------------------------------------------------------------


def test_mudanca_so_de_bot_e_espuria(dois_dbs):
    """XP de bots da liga (user_id < 0) muda pela simulação — não é dado real."""
    base, atual = dois_dbs
    _mk_db(base, flashcards=3, bot_xp=100, real_xp=50)
    _mk_db(atual, flashcards=3, bot_xp=999, real_xp=50)  # só o bot mudou
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "espurio", rel


def test_mudanca_do_usuario_real_e_dado_real(dois_dbs):
    """XP do usuário real (user_id > 0) em league_members É dado real."""
    base, atual = dois_dbs
    _mk_db(base, flashcards=3, bot_xp=100, real_xp=50)
    _mk_db(atual, flashcards=3, bot_xp=100, real_xp=80)  # usuário real mudou
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "dado_real", rel
    assert "league_members" in rel["tabelas_alteradas"]


# ---------------------------------------------------------------------------
# Filtro de colunas efêmeras (last_login): login não é dado de estudo
# ---------------------------------------------------------------------------


def test_mudanca_so_de_last_login_e_espuria(dois_dbs):
    """last_login muda a cada login (inclusive em testes) — não é dado real."""
    base, atual = dois_dbs
    _mk_db(base, flashcards=3, last_login="2026-01-01T00:00:00")
    _mk_db(atual, flashcards=3, last_login="2026-09-04T17:00:00")  # só o login mudou
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "espurio", rel


def test_mudanca_de_campo_real_do_usuario_e_dado_real(dois_dbs):
    """Alterar o nome do usuário (dado real) em users deve ser detectado."""
    base, atual = dois_dbs
    _mk_db(base, flashcards=3, user_nome="Antigo")
    _mk_db(atual, flashcards=3, user_nome="Novo Nome")  # dado real mudou
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "dado_real", rel
    assert "users" in rel["tabelas_alteradas"]


# ---------------------------------------------------------------------------
# Idempotência: db idêntico a si mesmo = espúrio
# ---------------------------------------------------------------------------


def test_db_identico_e_espurio(dois_dbs):
    base, atual = dois_dbs
    _mk_db(base, flashcards=4)
    _mk_db(atual, flashcards=4)
    rel = db_guard.diff_snapshots(db_guard._snapshot(atual), db_guard._snapshot(base))
    assert rel["decisao"] == "espurio", rel

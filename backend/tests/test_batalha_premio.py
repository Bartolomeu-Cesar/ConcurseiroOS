"""Testes do prêmio FIXO da batalha (1v1).

Garante que o prêmio:
- é sorteado uma única vez e persistido em battles.premio_idx;
- é o MESMO para os dois participantes e em toda visita (consistência);
- expõe papéis fixos: vencedor recebe, perdedor paga (meu_papel por usuário).
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime

import pytest

_tmp_db = tempfile.NamedTemporaryFile(suffix="_batalha_premio.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deps import get_user_id

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app
from routers.batalha.helpers import BATTLE_PRIZES, _ensure_battle_tables


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)

# user_id ativo controlável por teste (simula os dois participantes).
_current_user = {"id": 1}


def _override_user_id():
    return _current_user["id"]


@pytest.fixture(autouse=True)
def _ensure_db():
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    app.dependency_overrides[get_user_id] = _override_user_id
    _current_user["id"] = 1
    yield
    # Remove o override de get_user_id para não vazar para outros módulos de teste.
    app.dependency_overrides.pop(get_user_id, None)


def _criar_batalha_finalizada(codigo="PREMIO1", vencedor_id=10, perdedor_id=20):
    """Insere direto no DB uma batalha finalizada 1v1 com vencedor e perdedor."""
    conn = sqlite3.connect(_tmp_db.name)
    _ensure_battle_tables(conn)
    conn.execute("DELETE FROM battles WHERE codigo = ?", (codigo,))
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO battles (codigo, criador_id, titulo, materias, total_rodadas,
           rodada_atual, status, tempo_por_questao, max_jogadores, created_at, premio_idx)
           VALUES (?, ?, 'Duelo', '["X"]', 3, 3, 'finalizada', 30, 2, ?, -1)""",
        (codigo, vencedor_id, now),
    )
    bid = conn.execute("SELECT id FROM battles WHERE codigo = ?", (codigo,)).fetchone()[0]
    # Vencedor = mais pontos
    conn.execute(
        "INSERT INTO battle_players (battle_id, user_id, nome, avatar, pontos, acertos, erros, tempo_total_seg, posicao, joined_at) VALUES (?, ?, 'Alice', '', 300, 3, 0, 30, 1, ?)",
        (bid, vencedor_id, now),
    )
    conn.execute(
        "INSERT INTO battle_players (battle_id, user_id, nome, avatar, pontos, acertos, erros, tempo_total_seg, posicao, joined_at) VALUES (?, ?, 'Bob', '', 100, 1, 2, 40, 2, ?)",
        (bid, perdedor_id, now),
    )
    conn.commit()
    conn.close()
    return codigo


def test_premio_presente_e_valido():
    cod = _criar_batalha_finalizada("PREMIOA")
    r = client.get(f"/api/batalha/ranking/{cod}")
    assert r.status_code == 200
    premio = r.json()["premio"]
    assert premio is not None
    assert premio["texto"] in [p["texto"] for p in BATTLE_PRIZES]
    assert premio["quem_recebe_nome"] == "Alice"  # vencedor
    assert premio["quem_paga_nome"] == "Bob"       # perdedor


def test_premio_consistente_entre_visitas():
    """Mesmo prêmio em múltiplas consultas (fixado no servidor)."""
    cod = _criar_batalha_finalizada("PREMIOB")
    textos = set()
    for _ in range(5):
        premio = client.get(f"/api/batalha/ranking/{cod}").json()["premio"]
        textos.add((premio["emoji"], premio["texto"]))
    assert len(textos) == 1  # nunca muda


def test_premio_igual_para_ambos_participantes_com_papeis():
    """Os dois participantes veem o MESMO prêmio, com papéis opostos."""
    cod = _criar_batalha_finalizada("PREMIOC", vencedor_id=10, perdedor_id=20)

    _current_user["id"] = 10  # vencedor
    pv = client.get(f"/api/batalha/ranking/{cod}").json()["premio"]
    _current_user["id"] = 20  # perdedor
    pp = client.get(f"/api/batalha/ranking/{cod}").json()["premio"]

    # Mesmo prêmio para ambos
    assert pv["emoji"] == pp["emoji"]
    assert pv["texto"] == pp["texto"]
    # Papéis fixos e opostos
    assert pv["meu_papel"] == "recebe"
    assert pp["meu_papel"] == "paga"
    # Quem paga/recebe é igual nas duas visões
    assert pv["quem_recebe_id"] == pp["quem_recebe_id"] == 10
    assert pv["quem_paga_id"] == pp["quem_paga_id"] == 20


def test_premio_persistido_no_banco():
    cod = _criar_batalha_finalizada("PREMIOD")
    client.get(f"/api/batalha/ranking/{cod}")  # dispara o sorteio
    conn = sqlite3.connect(_tmp_db.name)
    idx = conn.execute("SELECT premio_idx FROM battles WHERE codigo = ?", (cod,)).fetchone()[0]
    conn.close()
    assert 0 <= idx < len(BATTLE_PRIZES)


def test_sem_premio_se_nao_finalizada():
    """Batalha ainda em andamento não expõe prêmio."""
    conn = sqlite3.connect(_tmp_db.name)
    _ensure_battle_tables(conn)
    now = datetime.now().isoformat()
    conn.execute("DELETE FROM battles WHERE codigo = 'PREMIOE'")
    conn.execute(
        """INSERT INTO battles (codigo, criador_id, titulo, materias, total_rodadas,
           rodada_atual, status, tempo_por_questao, max_jogadores, created_at, premio_idx)
           VALUES ('PREMIOE', 10, 'Duelo', '["X"]', 3, 1, 'em_andamento', 30, 2, ?, -1)""",
        (now,),
    )
    bid = conn.execute("SELECT id FROM battles WHERE codigo = 'PREMIOE'").fetchone()[0]
    conn.execute("INSERT INTO battle_players (battle_id, user_id, nome, avatar, pontos, acertos, erros, tempo_total_seg, posicao, joined_at) VALUES (?, 10, 'Alice', '', 100, 1, 0, 10, 1, ?)", (bid, now))
    conn.execute("INSERT INTO battle_players (battle_id, user_id, nome, avatar, pontos, acertos, erros, tempo_total_seg, posicao, joined_at) VALUES (?, 20, 'Bob', '', 50, 0, 1, 10, 2, ?)", (bid, now))
    conn.commit()
    conn.close()

    premio = client.get("/api/batalha/ranking/PREMIOE").json()["premio"]
    assert premio is None


def test_premio_deterministico_por_batalha():
    """O índice do prêmio é derivado do battle_id (determinístico): apagar e
    reconsultar sem premio_idx persistido produz o MESMO prêmio."""
    cod = _criar_batalha_finalizada("PREMIOF")
    p1 = client.get(f"/api/batalha/ranking/{cod}").json()["premio"]

    # Zera o premio_idx e consulta de novo — deve reconvergir para o mesmo.
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute("UPDATE battles SET premio_idx = -1 WHERE codigo = ?", (cod,))
    conn.commit()
    conn.close()

    p2 = client.get(f"/api/batalha/ranking/{cod}").json()["premio"]
    assert p1["texto"] == p2["texto"]
    assert p1["emoji"] == p2["emoji"]

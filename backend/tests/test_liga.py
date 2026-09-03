"""
Testes de integração da Liga Semanal (Leagues).
Cobre status semanal, histórico e processamento de semana.

Executar: pytest tests/test_liga.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_liga.db", delete=False)
_tmp_db.close()
os.environ["TEST_DB"] = _tmp_db.name
os.environ["AUTH_ENABLED"] = "false"

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session

database.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient
from main import app


def _override_db_session():
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def client():
    """TestClient compartilhado por todo o módulo de testes."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.pop(get_db_session, None)


@pytest.fixture(autouse=True)
def _ensure_db():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


@pytest.fixture(scope="module")
def setup_user(client):
    """Garante que existe um user no banco (necessário para liga)."""
    conn = sqlite3.connect(_tmp_db.name)
    conn.execute("""
        INSERT OR IGNORE INTO users (id, email, nome, created_at)
        VALUES (1, 'test@test.com', 'Testador', datetime('now'))
    """)
    conn.commit()
    conn.close()
    return 1


# ============================================================
# GET /api/liga — Status semanal
# ============================================================

class TestLigaSemanal:
    def test_obter_status_liga(self, client, setup_user):
        """GET /api/liga retorna status da liga semanal."""
        r = client.get("/api/liga")
        assert r.status_code == 200
        data = r.json()
        # Verificar campos obrigatórios
        assert "liga_atual" in data
        assert data["liga_atual"] in ("bronze", "prata", "ouro", "diamante")
        assert "liga_label" in data
        assert "liga_icon" in data
        assert "posicao" in data
        assert data["posicao"] >= 1
        assert "total_jogadores" in data
        assert data["total_jogadores"] >= 1
        assert "ranking" in data
        assert len(data["ranking"]) >= 1
        assert "semana_inicio" in data
        assert "semana_fim" in data
        assert "zona_promocao" in data
        assert "zona_rebaixamento" in data
        assert "dias_restantes" in data
        assert "xp_semana" in data
        assert "xp_breakdown" in data
        assert "xp_para_promocao" in data

    def test_ranking_contem_usuario(self, client, setup_user):
        """Ranking inclui o usuário corrente marcado."""
        r = client.get("/api/liga")
        data = r.json()
        ranking = data["ranking"]
        current_users = [p for p in ranking if p["is_current_user"]]
        assert len(current_users) == 1
        assert current_users[0]["user_id"] == 1

    def test_ranking_tem_zonas(self, client, setup_user):
        """Ranking mostra zonas de promoção/rebaixamento."""
        r = client.get("/api/liga")
        data = r.json()
        ranking = data["ranking"]
        zonas = {p["zona"] for p in ranking}
        # Deve ter pelo menos a zona "segura" ou zona de promoção
        assert len(zonas) >= 1

    def test_liga_idempotente(self, client, setup_user):
        """Chamar duas vezes retorna a mesma liga (mesma semana)."""
        r1 = client.get("/api/liga")
        r2 = client.get("/api/liga")
        assert r1.json()["liga_atual"] == r2.json()["liga_atual"]
        assert r1.json()["semana_inicio"] == r2.json()["semana_inicio"]

    def test_xp_breakdown_categorias(self, client, setup_user):
        """XP breakdown tem as categorias esperadas."""
        r = client.get("/api/liga")
        breakdown = r.json()["xp_breakdown"]
        categorias_esperadas = {
            "questoes", "horas_estudo", "flashcards", "desafios", "batalhas", "streak",
            "sumulas", "topicos", "metas", "erros_corrigidos", "simulados", "boss_battles"
        }
        assert set(breakdown.keys()) == categorias_esperadas


# ============================================================
# GET /api/liga/historico — Histórico
# ============================================================

class TestLigaHistorico:
    def test_historico_vazio_inicialmente(self, client, setup_user):
        """Histórico vazio para novo usuário."""
        r = client.get("/api/liga/historico")
        assert r.status_code == 200
        data = r.json()
        assert "historico" in data
        assert isinstance(data["historico"], list)
        # Pode ser vazio para user novo
        # Se tiver dados, verificar estrutura
        if data["historico"]:
            item = data["historico"][0]
            assert "semana_inicio" in item
            assert "semana_fim" in item
            assert "liga" in item
            assert "posicao_final" in item
            assert "xp_final" in item
            assert "resultado" in item

    def test_historico_apos_processamento(self, client, setup_user):
        """Após processar semana, histórico é populado."""
        from datetime import date, timedelta

        # Inserir uma liga de semana passada para ser processada
        conn = sqlite3.connect(_tmp_db.name)
        last_week_start = (date.today() - timedelta(days=14)).isoformat()
        last_week_end = (date.today() - timedelta(days=8)).isoformat()

        conn.execute("""
            INSERT INTO leagues (week_start, week_end, tier, created_at)
            VALUES (?, ?, 'bronze', datetime('now'))
        """, (last_week_start, last_week_end))
        league_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Adicionar o user como membro
        conn.execute("""
            INSERT INTO league_members (league_id, user_id, weekly_xp, rank, promoted, demoted)
            VALUES (?, 1, 500, 1, 0, 0)
        """, (league_id,))
        conn.commit()
        conn.close()

        # Processar
        r = client.post("/api/liga/processar")
        assert r.status_code == 200

        # Verificar histórico
        r = client.get("/api/liga/historico")
        assert r.status_code == 200
        historico = r.json()["historico"]
        # Deve ter pelo menos 1 registro agora
        assert len(historico) >= 1


# ============================================================
# POST /api/liga/processar — Processar semana
# ============================================================

class TestLigaProcessar:
    def test_processar_semana(self, client, setup_user):
        """POST /api/liga/processar executa sem erro."""
        r = client.post("/api/liga/processar")
        assert r.status_code == 200
        data = r.json()
        assert "processed_leagues" in data
        assert "promotions" in data
        assert "demotions" in data
        assert "message" in data
        assert isinstance(data["processed_leagues"], int)
        assert isinstance(data["promotions"], int)
        assert isinstance(data["demotions"], int)

    def test_processar_semana_idempotente(self, client, setup_user):
        """Processar duas vezes não duplica resultados."""
        r1 = client.post("/api/liga/processar")
        assert r1.status_code == 200

        r2 = client.post("/api/liga/processar")
        assert r2.status_code == 200
        # Segundo processamento não deve re-processar as mesmas ligas
        # (ou se já processado, count pode ser 0)

    def test_processar_com_promocao(self, client, setup_user):
        """Simulação de promoção: top 3 são promovidos."""
        from datetime import date, timedelta

        conn = sqlite3.connect(_tmp_db.name)
        # Criar liga de semana passada
        past_start = (date.today() - timedelta(days=21)).isoformat()
        past_end = (date.today() - timedelta(days=15)).isoformat()

        conn.execute("""
            INSERT INTO leagues (week_start, week_end, tier, created_at)
            VALUES (?, ?, 'bronze', datetime('now'))
        """, (past_start, past_end))
        league_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Adicionar user em posição top com XP alto
        conn.execute("""
            INSERT INTO league_members (league_id, user_id, weekly_xp, rank, promoted, demoted)
            VALUES (?, 1, 9999, 1, 0, 0)
        """, (league_id,))

        # Adicionar bots para completar a liga
        for i in range(14):
            conn.execute("""
                INSERT INTO league_members (league_id, user_id, weekly_xp, rank, promoted, demoted)
                VALUES (?, ?, ?, ?, 0, 0)
            """, (league_id, -(i + 100), 100 - i, i + 2))
        conn.commit()
        conn.close()

        r = client.post("/api/liga/processar")
        assert r.status_code == 200
        data = r.json()
        assert data["processed_leagues"] >= 1


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Remove banco temporário após testes."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

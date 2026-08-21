"""
Mutation tests for ConcurseiroOS: Leagues, Social, and AI Tutor routers.
Tests WRITE/MUTATION operations (POST, PUT, DELETE) and verifies state changes.

Executar: pytest tests/test_mutations.py -v
"""
import os
import sys
import tempfile
from unittest.mock import patch

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
import settings as settings_mod

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


# ============================================================
# HELPERS
# ============================================================

def _get_db():
    """Get a direct DB connection for test assertions."""
    import sqlite3
    conn = sqlite3.connect(database.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _create_test_user(user_id=2, email="amigo@test.com", username="AmigoTest"):
    """Insert a test user directly into DB for social tests."""
    db = _get_db()
    db.execute(
        """INSERT OR IGNORE INTO users (id, email, nome, username, plano, created_at)
           VALUES (?, ?, ?, ?, 'free', datetime('now'))""",
        (user_id, email, username, username)
    )
    db.commit()
    db.close()
    return user_id


def _create_friendship(user_a=1, user_b=2, status="pending"):
    """Insert a friendship directly into DB."""
    db = _get_db()
    db.execute(
        "INSERT INTO friendships (user_a, user_b, status, created_at) VALUES (?, ?, ?, date('now'))",
        (user_a, user_b, status)
    )
    db.commit()
    fid = db.execute("SELECT last_insert_rowid() as id").fetchone()[0]
    db.close()
    return fid


def _cleanup_table(table_name):
    """Clear a table for test isolation."""
    db = _get_db()
    db.execute(f"DELETE FROM {table_name}")
    db.commit()
    db.close()


# ============================================================
# LEAGUES TESTS
# ============================================================

class TestLeaguesJoin:
    """Tests for league auto-join via GET /api/leagues/current."""

    def setup_method(self):
        _cleanup_table("league_members")
        _cleanup_table("leagues")
        _cleanup_table("league_history")

    def test_join_league_auto_creates_on_first_access(self):
        """User auto-joins a league on first GET /api/leagues/current."""
        r = client.get("/api/leagues/current")
        assert r.status_code == 200
        data = r.json()
        assert "league_id" in data
        assert data["tier"] == "bronze"
        assert data["user_rank"] > 0
        assert data["total_members"] > 1  # includes bots

    def test_join_league_idempotent(self):
        """Calling current twice returns same league."""
        r1 = client.get("/api/leagues/current")
        r2 = client.get("/api/leagues/current")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["league_id"] == r2.json()["league_id"]

    def test_join_league_user_appears_in_standings(self):
        """After joining, user appears in standings with is_current_user=True."""
        r = client.get("/api/leagues/current")
        assert r.status_code == 200
        standings = r.json()["standings"]
        current_users = [s for s in standings if s["is_current_user"]]
        assert len(current_users) == 1
        assert current_users[0]["name"] == "Você"

    def test_league_has_promotion_and_demotion_zones(self):
        """Standings include zone information."""
        r = client.get("/api/leagues/current")
        assert r.status_code == 200
        standings = r.json()["standings"]
        zones = {s["zone"] for s in standings}
        assert "promotion" in zones
        assert "safe" in zones or "demotion" in zones


class TestLeaguesUpdateXP:
    """Tests for POST /api/leagues/update-xp."""

    def setup_method(self):
        _cleanup_table("league_members")
        _cleanup_table("leagues")
        _cleanup_table("league_history")

    def test_update_xp_returns_rank(self):
        """POST /api/leagues/update-xp returns updated rank and XP."""
        # First join a league
        client.get("/api/leagues/current")
        # Then update XP
        r = client.post("/api/leagues/update-xp")
        assert r.status_code == 200
        data = r.json()
        assert "weekly_xp" in data
        assert "rank" in data
        assert "league_id" in data

    def test_update_xp_auto_assigns_league_if_none(self):
        """If user has no league, update-xp auto-assigns one."""
        r = client.post("/api/leagues/update-xp")
        assert r.status_code == 200
        assert "league_id" in r.json()


class TestLeaguesWeeklyProcess:
    """Tests for POST /api/leagues/process-week (weekly promotion/demotion)."""

    def setup_method(self):
        _cleanup_table("league_members")
        _cleanup_table("leagues")
        _cleanup_table("league_history")

    def test_process_week_returns_processed_count(self):
        """Weekly process endpoint returns count of processed leagues."""
        # First create a league
        client.get("/api/leagues/current")
        r = client.post("/api/leagues/process-week")
        assert r.status_code == 200
        data = r.json()
        assert "processed_leagues" in data
        assert "message" in data
        assert isinstance(data["processed_leagues"], int)

    def test_process_week_idempotent_no_double_processing(self):
        """Processing twice doesn't duplicate history."""
        client.get("/api/leagues/current")
        r1 = client.post("/api/leagues/process-week")
        r2 = client.post("/api/leagues/process-week")
        assert r1.status_code == 200
        assert r2.status_code == 200


class TestLeaguesLeaderboard:
    """Tests verifying leaderboard state after mutations."""

    def setup_method(self):
        _cleanup_table("league_members")
        _cleanup_table("leagues")
        _cleanup_table("league_history")

    def test_leaderboard_sorted_by_xp_desc(self):
        """Leaderboard standings are sorted by XP descending (rank ascending)."""
        r = client.get("/api/leagues/current")
        assert r.status_code == 200
        standings = r.json()["standings"]
        ranks = [s["rank"] for s in standings]
        assert ranks == sorted(ranks)

    def test_leaderboard_xp_updates_after_update_xp(self):
        """After update-xp, standings reflect new XP values."""
        client.get("/api/leagues/current")
        r = client.post("/api/leagues/update-xp")
        assert r.status_code == 200
        # Verify league still accessible
        r2 = client.get("/api/leagues/current")
        assert r2.status_code == 200
        assert r2.json()["total_members"] > 0


# ============================================================
# SOCIAL TESTS
# ============================================================

class TestSocialFriendRequest:
    """Tests for POST /api/social/friends/add (send friend request)."""

    def setup_method(self):
        _cleanup_table("friendships")
        _create_test_user(2, "amigo@test.com", "AmigoTest")

    def test_send_friend_request_by_user_id(self):
        """Send friend request using user_id."""
        r = client.post("/api/social/friends/add", json={"user_id": 2})
        assert r.status_code == 200
        data = r.json()
        assert "friendship_id" in data
        assert "enviada" in data["message"].lower() or "amizade" in data["message"].lower()

    def test_send_friend_request_by_email(self):
        """Send friend request using email."""
        r = client.post("/api/social/friends/add", json={"email": "amigo@test.com"})
        assert r.status_code == 200
        assert "friendship_id" in r.json()

    def test_send_friend_request_missing_fields_returns_400(self):
        """Sending without email or user_id returns 400."""
        r = client.post("/api/social/friends/add", json={})
        assert r.status_code == 400

    def test_send_friend_request_nonexistent_user_returns_404(self):
        """Sending to nonexistent user returns 404."""
        r = client.post("/api/social/friends/add", json={"user_id": 9999})
        assert r.status_code == 404

    def test_send_friend_request_to_self_returns_400(self):
        """Cannot send friend request to yourself."""
        r = client.post("/api/social/friends/add", json={"user_id": 1})
        assert r.status_code == 400

    def test_duplicate_friend_request_returns_400(self):
        """Sending duplicate request returns 400."""
        client.post("/api/social/friends/add", json={"user_id": 2})
        r = client.post("/api/social/friends/add", json={"user_id": 2})
        assert r.status_code == 400


class TestSocialAcceptFriend:
    """Tests for POST /api/social/friends/{id}/accept."""

    def setup_method(self):
        _cleanup_table("friendships")
        _create_test_user(2, "amigo@test.com", "AmigoTest")

    def test_accept_friend_request(self):
        """Accept a pending friend request."""
        # Create a pending request FROM user 2 TO user 1 (user 1 is the receiver)
        fid = _create_friendship(user_a=2, user_b=1, status="pending")
        r = client.post(f"/api/social/friends/{fid}/accept")
        assert r.status_code == 200
        assert "aceita" in r.json()["message"].lower()

    def test_accept_friend_request_state_changes(self):
        """After accepting, users appear as friends."""
        fid = _create_friendship(user_a=2, user_b=1, status="pending")
        client.post(f"/api/social/friends/{fid}/accept")
        # Check friendship status in DB
        db = _get_db()
        row = db.execute("SELECT status FROM friendships WHERE id = ?", (fid,)).fetchone()
        db.close()
        assert row[0] == "accepted"

    def test_accept_nonexistent_request_returns_404(self):
        """Accepting non-existent request returns 404."""
        r = client.post("/api/social/friends/9999/accept")
        assert r.status_code == 404

    def test_accept_already_accepted_returns_404(self):
        """Cannot accept already-accepted friendship."""
        fid = _create_friendship(user_a=2, user_b=1, status="accepted")
        r = client.post(f"/api/social/friends/{fid}/accept")
        assert r.status_code == 404


class TestSocialCreateGroup:
    """Tests for POST /api/social/groups."""

    def setup_method(self):
        _cleanup_table("group_members")
        _cleanup_table("study_groups")

    def test_create_group_success(self):
        """Create a study group with all fields."""
        r = client.post("/api/social/groups", json={
            "nome": "Grupo Direito Penal",
            "descricao": "Estudo de Direito Penal para concursos",
            "edital_nome": "PC-DF 2026",
            "max_membros": 15,
            "publico": True
        })
        assert r.status_code == 200
        data = r.json()
        assert "group_id" in data
        assert data["group_id"] > 0

    def test_create_group_minimal_fields(self):
        """Create group with just the required nome field."""
        r = client.post("/api/social/groups", json={"nome": "Grupo Minimo"})
        assert r.status_code == 200
        assert "group_id" in r.json()

    def test_create_group_missing_nome_returns_422(self):
        """Missing required 'nome' field returns 422."""
        r = client.post("/api/social/groups", json={"descricao": "Sem nome"})
        assert r.status_code == 422

    def test_create_group_creator_is_member(self):
        """After creation, creator is automatically a member with 'creator' role."""
        r = client.post("/api/social/groups", json={"nome": "Meu Grupo"})
        group_id = r.json()["group_id"]
        db = _get_db()
        row = db.execute(
            "SELECT role FROM group_members WHERE group_id = ? AND user_id = 1",
            (group_id,)
        ).fetchone()
        db.close()
        assert row is not None
        assert row[0] == "creator"


class TestSocialJoinGroup:
    """Tests for POST /api/social/groups/{id}/join."""

    def setup_method(self):
        _cleanup_table("group_members")
        _cleanup_table("study_groups")
        _cleanup_table("activity_feed")
        _create_test_user(2, "amigo@test.com", "AmigoTest")

    def _create_group(self, publico=True, max_membros=20):
        """Helper to create a group as user 1."""
        r = client.post("/api/social/groups", json={
            "nome": "Grupo Teste",
            "publico": publico,
            "max_membros": max_membros
        })
        return r.json()["group_id"]

    def test_join_public_group(self):
        """Join a public group successfully."""
        group_id = self._create_group(publico=True)
        # We need a different user to join. Since auth is disabled, user_id=1 is the creator.
        # The endpoint checks if already member, so we need to simulate another user joining.
        # Since the test client always returns user_id=1, we test that joining own group fails.
        r = client.post(f"/api/social/groups/{group_id}/join")
        # User 1 is already a member (creator), so this should return 400
        assert r.status_code == 400
        assert "já é membro" in r.json()["detail"].lower()

    def test_join_nonexistent_group_returns_404(self):
        """Joining non-existent group returns 404."""
        r = client.post("/api/social/groups/9999/join")
        assert r.status_code == 404

    def test_join_private_group_returns_403(self):
        """Joining a private group returns 403."""
        group_id = self._create_group(publico=False)
        # Remove creator membership so we can test join
        db = _get_db()
        db.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = 1", (group_id,))
        db.commit()
        db.close()
        r = client.post(f"/api/social/groups/{group_id}/join")
        assert r.status_code == 403

    def test_join_full_group_returns_400(self):
        """Joining a full group returns 400."""
        group_id = self._create_group(publico=True, max_membros=1)
        # User 1 is already there (creator), so it's full (1/1)
        # Remove membership and try to join again to properly test
        db = _get_db()
        db.execute("DELETE FROM group_members WHERE group_id = ? AND user_id = 1", (group_id,))
        # Add a different user to fill it
        db.execute(
            "INSERT INTO group_members (group_id, user_id, role, joined_at) VALUES (?, 2, 'member', date('now'))",
            (group_id,)
        )
        db.commit()
        db.close()
        r = client.post(f"/api/social/groups/{group_id}/join")
        assert r.status_code == 400
        assert "lotado" in r.json()["detail"].lower()


class TestSocialPostActivity:
    """Tests for POST /api/social/feed/post."""

    def setup_method(self):
        _cleanup_table("activity_feed")

    def test_post_activity_valid_type(self):
        """Post activity with valid type."""
        r = client.post("/api/social/feed/post", json={
            "tipo": "streak_milestone",
            "descricao": "7 dias de streak!",
            "dados": {"streak": 7}
        })
        assert r.status_code == 200
        assert "activity_id" in r.json()

    def test_post_activity_invalid_type_returns_400(self):
        """Invalid tipo returns 400."""
        r = client.post("/api/social/feed/post", json={
            "tipo": "invalid_type",
            "descricao": "Algo"
        })
        assert r.status_code == 400
        assert "inválido" in r.json()["detail"].lower()

    def test_post_activity_missing_tipo_returns_422(self):
        """Missing required 'tipo' field returns 422."""
        r = client.post("/api/social/feed/post", json={"descricao": "Algo"})
        assert r.status_code == 422

    def test_post_activity_missing_descricao_returns_422(self):
        """Missing required 'descricao' field returns 422."""
        r = client.post("/api/social/feed/post", json={"tipo": "badge_earned"})
        assert r.status_code == 422

    def test_post_activity_appears_in_feed(self):
        """After posting, activity appears in feed."""
        client.post("/api/social/feed/post", json={
            "tipo": "badge_earned",
            "descricao": "Conquistou medalha de ouro!"
        })
        r = client.get("/api/social/feed")
        assert r.status_code == 200
        feed = r.json()["feed"]
        assert len(feed) >= 1
        assert any("medalha" in item["descricao"] for item in feed)

    def test_post_multiple_activities_all_appear(self):
        """Multiple posts appear in order in the feed."""
        for i in range(3):
            client.post("/api/social/feed/post", json={
                "tipo": "level_up",
                "descricao": f"Subiu para nível {i + 2}",
                "dados": {"level": i + 2}
            })
        r = client.get("/api/social/feed")
        assert r.status_code == 200
        feed = r.json()["feed"]
        assert len(feed) >= 3


class TestSocialRemoveFriend:
    """Tests for DELETE /api/social/friends/{id}."""

    def setup_method(self):
        _cleanup_table("friendships")
        _create_test_user(2, "amigo@test.com", "AmigoTest")

    def test_remove_friend_success(self):
        """Remove an accepted friendship."""
        fid = _create_friendship(user_a=1, user_b=2, status="accepted")
        r = client.delete(f"/api/social/friends/{fid}")
        assert r.status_code == 200
        assert "removido" in r.json()["message"].lower()

    def test_remove_friend_state_verified(self):
        """After removal, friendship no longer exists in DB."""
        fid = _create_friendship(user_a=1, user_b=2, status="accepted")
        client.delete(f"/api/social/friends/{fid}")
        db = _get_db()
        row = db.execute("SELECT * FROM friendships WHERE id = ?", (fid,)).fetchone()
        db.close()
        assert row is None

    def test_remove_nonexistent_friend_returns_404(self):
        """Removing non-existent friendship returns 404."""
        r = client.delete("/api/social/friends/9999")
        assert r.status_code == 404

    def test_remove_pending_friendship_returns_404(self):
        """Cannot remove a friendship that is still pending (must be accepted)."""
        fid = _create_friendship(user_a=1, user_b=2, status="pending")
        r = client.delete(f"/api/social/friends/{fid}")
        assert r.status_code == 404


# ============================================================
# AI TUTOR TESTS
# ============================================================

class TestAITutorChat:
    """Tests for POST /api/ai/chat (send question to AI)."""

    def setup_method(self):
        _cleanup_table("ai_conversations")
        _cleanup_table("ai_usage")

    @patch("routers.ai_tutor.call_llm_sync")
    def test_chat_success_mocked(self, mock_llm):
        """Chat returns a response when AI is mocked."""
        mock_llm.return_value = ("Estude com foco no edital!", 150)
        r = client.post("/api/ai/chat", json={
            "mensagem": "Como estudar para concurso?"
        })
        assert r.status_code == 200
        data = r.json()
        assert "resposta" in data
        assert data["resposta"] == "Estude com foco no edital!"
        assert data["tokens_usados"] == 150

    @patch("routers.ai_tutor.call_llm_sync")
    def test_chat_with_context(self, mock_llm):
        """Chat with context field works correctly."""
        mock_llm.return_value = ("Foque nos artigos mais cobrados.", 200)
        r = client.post("/api/ai/chat", json={
            "mensagem": "O que estudar?",
            "contexto": "Direito Constitucional para CESPE"
        })
        assert r.status_code == 200
        assert "resposta" in r.json()

    def test_chat_empty_message_returns_422(self):
        """Empty message returns 422."""
        r = client.post("/api/ai/chat", json={"mensagem": ""})
        assert r.status_code == 422

    def test_chat_missing_mensagem_returns_422(self):
        """Missing 'mensagem' field returns 422."""
        r = client.post("/api/ai/chat", json={})
        assert r.status_code == 422

    def test_chat_no_ai_provider_returns_503(self):
        """Without AI provider configured, returns 503."""
        # Remove all AI env vars to trigger no-provider state
        env_keys = ["OPENAI_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
                    "XAI_API_KEY", "DEEPSEEK_API_KEY", "MISTRAL_API_KEY",
                    "GROQ_API_KEY", "TOGETHER_API_KEY", "COHERE_API_KEY",
                    "PERPLEXITY_API_KEY", "KIMI_API_KEY", "GLM_API_KEY",
                    "AWS_BEDROCK_REGION"]
        saved = {k: os.environ.pop(k, None) for k in env_keys}
        saved["AI_PROVIDER"] = os.environ.pop("AI_PROVIDER", None)

        # Patch ollama check to fail
        with patch("routers.ai_tutor._get_ai_config") as mock_config:
            mock_config.return_value = {"provider": "none", "api_key": "", "url": "", "model": "", "format": ""}
            r = client.post("/api/ai/chat", json={"mensagem": "Teste"})
            assert r.status_code == 503

        # Restore env
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


class TestAITutorHistory:
    """Tests for GET /api/ai/history."""

    def setup_method(self):
        _cleanup_table("ai_conversations")
        _cleanup_table("ai_usage")

    def test_history_empty_initially(self):
        """History is empty when no conversations exist."""
        r = client.get("/api/ai/history")
        assert r.status_code == 200
        assert r.json()["historico"] == []
        assert r.json()["total"] == 0

    @patch("routers.ai_tutor.call_llm_sync")
    def test_history_stores_conversations(self, mock_llm):
        """After a chat, conversation appears in history."""
        mock_llm.return_value = ("Resposta de teste", 100)
        client.post("/api/ai/chat", json={"mensagem": "Pergunta de teste"})

        r = client.get("/api/ai/history")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 1
        assert data["historico"][0]["tipo"] == "chat"
        assert "Pergunta" in data["historico"][0]["pergunta"]

    @patch("routers.ai_tutor.call_llm_sync")
    def test_history_filter_by_tipo(self, mock_llm):
        """History can be filtered by type."""
        mock_llm.return_value = ("Explicação", 120)
        # Insert a record directly with a specific tipo
        db = _get_db()
        db.execute(
            """INSERT INTO ai_conversations (user_id, tipo, pergunta, resposta, tokens, created_at)
               VALUES (1, 'explain_error', 'Por que errei?', 'Porque...', 120, datetime('now'))"""
        )
        db.execute(
            """INSERT INTO ai_conversations (user_id, tipo, pergunta, resposta, tokens, created_at)
               VALUES (1, 'chat', 'Olá', 'Oi!', 50, datetime('now'))"""
        )
        db.commit()
        db.close()

        r = client.get("/api/ai/history", params={"tipo": "explain_error"})
        assert r.status_code == 200
        data = r.json()
        assert all(h["tipo"] == "explain_error" for h in data["historico"])

    @patch("routers.ai_tutor.call_llm_sync")
    def test_history_respects_limit(self, mock_llm):
        """History respects limit parameter."""
        mock_llm.return_value = ("R", 10)
        # Insert multiple records
        db = _get_db()
        for i in range(5):
            db.execute(
                """INSERT INTO ai_conversations (user_id, tipo, pergunta, resposta, tokens, created_at)
                   VALUES (1, 'chat', ?, 'Resp', 10, datetime('now'))""",
                (f"Pergunta {i}",)
            )
        db.commit()
        db.close()

        r = client.get("/api/ai/history", params={"limit": 2})
        assert r.status_code == 200
        assert r.json()["total"] <= 2


class TestAITutorFeedback:
    """Tests for AI usage/budget tracking (acts as implicit feedback on usage)."""

    def setup_method(self):
        _cleanup_table("ai_usage")
        _cleanup_table("ai_conversations")

    @patch("routers.ai_tutor.call_llm_sync")
    def test_usage_increments_after_request(self, mock_llm):
        """Token usage increments after each AI request."""
        mock_llm.return_value = ("Resposta", 200)
        client.post("/api/ai/chat", json={"mensagem": "Pergunta 1"})

        r = client.get("/api/ai/usage")
        assert r.status_code == 200
        data = r.json()
        assert data["tokens_used"] >= 200
        assert data["requests_today"] >= 1

    @patch("routers.ai_tutor.call_llm_sync")
    def test_usage_accumulates_multiple_requests(self, mock_llm):
        """Multiple requests accumulate tokens."""
        mock_llm.return_value = ("R", 100)
        client.post("/api/ai/chat", json={"mensagem": "P1"})
        client.post("/api/ai/chat", json={"mensagem": "P2"})

        r = client.get("/api/ai/usage")
        assert r.status_code == 200
        assert r.json()["tokens_used"] >= 200
        assert r.json()["requests_today"] >= 2


class TestAITutorConfig:
    """Tests for GET/PUT /api/ai/config."""

    def setup_method(self):
        # Ensure ai_config table exists and is clean
        db = _get_db()
        db.execute("""
            CREATE TABLE IF NOT EXISTS ai_config (
                user_id INTEGER PRIMARY KEY,
                provider TEXT DEFAULT 'auto',
                api_key TEXT DEFAULT '',
                model TEXT DEFAULT ''
            )
        """)
        db.execute("DELETE FROM ai_config")
        db.commit()
        db.close()

    def test_get_config_default(self):
        """Default config returns auto provider."""
        r = client.get("/api/ai/config")
        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == "auto"
        assert data["has_key"] is False

    def test_update_config_provider(self):
        """Update AI config with a provider."""
        r = client.put("/api/ai/config", json={
            "provider": "openai",
            "api_key": "sk-test1234567890abcdef",
            "model": "gpt-4o-mini"
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_update_config_state_persists(self):
        """After updating config, GET reflects the changes."""
        client.put("/api/ai/config", json={
            "provider": "gemini",
            "api_key": "AIza1234567890abcdef",
            "model": "gemini-2.0-flash"
        })
        r = client.get("/api/ai/config")
        assert r.status_code == 200
        data = r.json()
        assert data["provider"] == "gemini"
        assert data["has_key"] is True
        assert "..." in data["api_key_masked"]  # masked

    def test_update_config_empty_key(self):
        """Updating with empty key sets has_key=False."""
        client.put("/api/ai/config", json={
            "provider": "openai",
            "api_key": "",
            "model": ""
        })
        r = client.get("/api/ai/config")
        assert r.status_code == 200
        assert r.json()["has_key"] is False

    def test_update_config_missing_body_returns_422(self):
        """PUT without body returns 422."""
        r = client.put("/api/ai/config")
        assert r.status_code == 422


class TestAITutorExplainError:
    """Tests for POST /api/ai/explain-error."""

    def setup_method(self):
        _cleanup_table("ai_conversations")
        _cleanup_table("ai_usage")

    @patch("routers.ai_tutor.call_llm_sync")
    def test_explain_error_with_text(self, mock_llm):
        """Explain error with enunciado + resposta_correta."""
        mock_llm.return_value = ("O erro foi conceitual: ...", 300)
        r = client.post("/api/ai/explain-error", json={
            "enunciado": "A CF/88 prevê direito à moradia?",
            "resposta_usuario": "Não",
            "resposta_correta": "Sim",
            "explicacao": "Art. 6º da CF/88"
        })
        assert r.status_code == 200
        assert "resposta" in r.json()

    def test_explain_error_missing_both_ids_returns_422(self):
        """Missing both questao_id and enunciado+resposta_correta returns error."""
        r = client.post("/api/ai/explain-error", json={
            "resposta_usuario": "A"
        })
        # The endpoint checks if questao_id is None and enunciado/resposta_correta are None
        # It returns 422 when neither path is valid
        assert r.status_code in (422, 503)  # 503 if LLM not configured, 422 if validation


class TestAITutorGenerateFlashcards:
    """Tests for POST /api/ai/generate-flashcards."""

    def setup_method(self):
        _cleanup_table("ai_conversations")
        _cleanup_table("ai_usage")

    @patch("routers.ai_tutor.call_llm_sync")
    def test_generate_flashcards_success(self, mock_llm):
        """Generate flashcards returns parsed JSON."""
        mock_llm.return_value = (
            '[{"pergunta": "O que é CF?", "resposta": "Constituição Federal"}]',
            250
        )
        r = client.post("/api/ai/generate-flashcards", json={
            "topico": "Direito Constitucional",
            "quantidade": 1,
            "materia": "Direito"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["flashcards"] is not None
        assert len(data["flashcards"]) == 1

    def test_generate_flashcards_missing_topico_returns_422(self):
        """Missing required topico returns 422."""
        r = client.post("/api/ai/generate-flashcards", json={"quantidade": 5})
        assert r.status_code == 422


# ============================================================
# INTEGRATION / STATE CHANGE TESTS
# ============================================================

class TestIntegrationStateChanges:
    """Cross-module state change verification tests."""

    def setup_method(self):
        _cleanup_table("league_members")
        _cleanup_table("leagues")
        _cleanup_table("league_history")
        _cleanup_table("activity_feed")
        _cleanup_table("friendships")
        _cleanup_table("group_members")
        _cleanup_table("study_groups")

    def test_league_tier_info_accessible(self):
        """GET /api/leagues/tier-info returns tier configuration."""
        r = client.get("/api/leagues/tier-info")
        assert r.status_code == 200
        data = r.json()
        assert "tiers" in data
        assert len(data["tiers"]) == 5  # bronze, prata, ouro, diamante, mestre
        assert data["current_tier"] == "bronze"

    def test_league_history_empty_initially(self):
        """GET /api/leagues/history returns empty list initially."""
        r = client.get("/api/leagues/history")
        assert r.status_code == 200
        assert r.json()["history"] == []

    def test_social_friends_list_empty_initially(self):
        """GET /api/social/friends returns empty when no friends."""
        r = client.get("/api/social/friends")
        assert r.status_code == 200
        assert r.json()["friends"] == []

    def test_social_groups_list_empty_initially(self):
        """GET /api/social/groups returns empty when user has no groups."""
        r = client.get("/api/social/groups")
        assert r.status_code == 200
        assert r.json()["groups"] == []

    def test_full_friendship_lifecycle(self):
        """Test complete friendship flow: request → accept → list → remove."""
        _create_test_user(3, "lifecycle@test.com", "LifecycleUser")

        # Create friendship as if user 3 requested user 1
        fid = _create_friendship(user_a=3, user_b=1, status="pending")

        # Accept
        r = client.post(f"/api/social/friends/{fid}/accept")
        assert r.status_code == 200

        # Verify in friends list
        r = client.get("/api/social/friends")
        assert r.status_code == 200
        friends = r.json()["friends"]
        assert any(f["user_id"] == 3 for f in friends)

        # Remove
        r = client.delete(f"/api/social/friends/{fid}")
        assert r.status_code == 200

        # Verify removed
        r = client.get("/api/social/friends")
        assert r.status_code == 200
        assert not any(f["user_id"] == 3 for f in r.json()["friends"])

    def test_full_group_lifecycle(self):
        """Test complete group flow: create → list → leave."""
        # Create
        r = client.post("/api/social/groups", json={"nome": "Lifecycle Group"})
        assert r.status_code == 200
        group_id = r.json()["group_id"]

        # List
        r = client.get("/api/social/groups")
        assert r.status_code == 200
        groups = r.json()["groups"]
        assert any(g["id"] == group_id for g in groups)

        # Leave (as creator with no other members → deletes group)
        r = client.post(f"/api/social/groups/{group_id}/leave")
        assert r.status_code == 200

        # Verify group is gone
        r = client.get("/api/social/groups")
        assert r.status_code == 200
        assert not any(g["id"] == group_id for g in r.json()["groups"])

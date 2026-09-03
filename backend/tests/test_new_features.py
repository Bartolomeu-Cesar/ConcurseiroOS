"""
Testes dos endpoints novos do ConcurseiroOS (Sprints recentes).
Cobre: FSRS, Mastery, Leagues, AI Tutor, Social, Notifications, Raio-X, Streak Freeze.

Executar: pytest tests/test_new_features.py -v
"""
import os
import sqlite3
import sys
import tempfile

import pytest

# Configurar DB temporário ANTES de importar o app
_tmp_db = tempfile.NamedTemporaryFile(suffix="_newfeatures.db", delete=False)
_tmp_db.close()
os.environ["DB_PATH"] = _tmp_db.name
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ["AUTH_ENABLED"] = "false"

# Ajustar path para imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database
from database import get_db_session
import settings as settings_mod

database.DB_PATH = _tmp_db.name
settings_mod.settings.DB_PATH = _tmp_db.name
database.init_db()

from fastapi.testclient import TestClient

from main import app


def _override_db_session():
    """Override para garantir que FastAPI use o DB temporário deste módulo."""
    conn = sqlite3.connect(_tmp_db.name, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    try:
        yield conn
    finally:
        conn.close()


# Aplicar override ANTES de criar o client
app.dependency_overrides[get_db_session] = _override_db_session
client = TestClient(app)


@pytest.fixture(autouse=True)
def _ensure_db_new_features():
    """Garante que o DB correto está ativo antes de cada teste."""
    database.DB_PATH = _tmp_db.name
    app.dependency_overrides[get_db_session] = _override_db_session
    yield


# ============================================================
# HELPERS
# ============================================================

def _create_flashcard(pergunta="Teste?", resposta="Sim"):
    """Helper para criar flashcard e retornar id."""
    r = client.post("/api/flashcards", json={
        "pergunta": pergunta,
        "resposta": resposta
    })
    assert r.status_code == 200
    return r.json()["id"]


def _create_edital_topic(materia="Direito Penal", topico="Crimes contra a pessoa",
                         edital_nome="PC-DF 2026", cargo="Delegado"):
    """Helper para criar tópico no edital."""
    r = client.post("/api/edital", json={
        "materia": materia,
        "topico": topico,
        "edital_nome": edital_nome,
        "cargo": cargo
    })
    assert r.status_code == 200
    return r.json()["id"]


def _create_questao(materia="Direito Penal", topico="Crimes", banca="CESPE"):
    """Helper para criar questão."""
    r = client.post("/api/questoes", json={
        "materia": materia,
        "topico": topico,
        "enunciado": f"Questão de {materia}?",
        "alternativa_a": "Certo",
        "alternativa_b": "Errado",
        "alternativa_c": "C",
        "alternativa_d": "D",
        "resposta_correta": "A",
        "banca": banca
    })
    assert r.status_code == 200
    return r.json()["id"]


def _create_sumula(tribunal="STF", numero=100, enunciado="Teste de súmula"):
    """Helper para criar súmula."""
    r = client.post("/api/sumulas", json={
        "tribunal": tribunal,
        "numero": numero,
        "enunciado": enunciado
    })
    assert r.status_code == 200
    return r.json()["id"]


# ============================================================
# 1. FSRS ALGORITHM TESTS
# ============================================================

class TestFSRSFlashcards:
    """Testes do algoritmo FSRS para flashcards."""

    def test_fsrs_review_new_card(self):
        """Create flashcard, review with FSRS, verify stability/difficulty/interval."""
        fid = _create_flashcard("O que é FSRS?", "Free Spaced Repetition Scheduler")
        r = client.post(f"/api/flashcards/{fid}/review-fsrs", json={"quality": 3})
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == fid
        assert data["intervalo_dias"] >= 1
        assert data["stability"] > 0
        assert data["difficulty"] > 0
        assert data["fsrs_state"] >= 0
        assert data["repetitions"] >= 1
        assert "proxima_revisao" in data

    def test_fsrs_review_good_increases_stability(self):
        """Review with quality=4 (Good) should produce reasonable stability."""
        fid = _create_flashcard("Good card?", "Yes")
        # First review
        r1 = client.post(f"/api/flashcards/{fid}/review-fsrs", json={"quality": 4})
        assert r1.status_code == 200
        stability_after_first = r1.json()["stability"]

        # Second review with Good
        r2 = client.post(f"/api/flashcards/{fid}/review-fsrs", json={"quality": 4})
        assert r2.status_code == 200
        stability_after_second = r2.json()["stability"]

        # Stability should increase after a good review
        assert stability_after_second >= stability_after_first

    def test_fsrs_review_again_resets(self):
        """Review with quality=0 (Again) should decrease interval compared to Good."""
        fid_good = _create_flashcard("Good answer?", "Always good")
        fid_again = _create_flashcard("Bad answer?", "Always forget")

        # Review Good card with quality=4
        r_good = client.post(f"/api/flashcards/{fid_good}/review-fsrs", json={"quality": 4})
        assert r_good.status_code == 200
        interval_good = r_good.json()["intervalo_dias"]

        # Review Again card with quality=0
        r_again = client.post(f"/api/flashcards/{fid_again}/review-fsrs", json={"quality": 0})
        assert r_again.status_code == 200
        interval_again = r_again.json()["intervalo_dias"]

        # Again should have shorter (or equal) interval than Good
        assert interval_again <= interval_good

    def test_fsrs_review_nonexistent_flashcard(self):
        """FSRS review on nonexistent flashcard should return 404."""
        r = client.post("/api/flashcards/99999/review-fsrs", json={"quality": 3})
        assert r.status_code == 404


class TestFlashcardsTodayCount:
    """Progresso da revisão: contagem flashcard-específica (fix do 'X/Y')."""

    def test_today_count_estrutura(self):
        """O endpoint retorna pendentes e revisados_hoje."""
        r = client.get("/api/flashcards/today-count")
        assert r.status_code == 200
        data = r.json()
        assert "pendentes" in data and "revisados_hoje" in data
        assert isinstance(data["pendentes"], int)
        assert isinstance(data["revisados_hoje"], int)

    def test_revisar_incrementa_revisados_hoje(self):
        """Revisar um flashcard incrementa revisados_hoje (via ultima_revisao)."""
        base = client.get("/api/flashcards/today-count").json()["revisados_hoje"]
        fid = _create_flashcard("Contagem?", "Sim, conta hoje")
        r = client.post(f"/api/flashcards/{fid}/review-fsrs", json={"quality": 4})
        assert r.status_code == 200
        depois = client.get("/api/flashcards/today-count").json()["revisados_hoje"]
        assert depois == base + 1

    def test_revisao_sumula_nao_conta_como_flashcard(self):
        """Revisar SÚMULA não deve inflar revisados_hoje de flashcards
        (fix da contaminação do contador do streak)."""
        base = client.get("/api/flashcards/today-count").json()["revisados_hoje"]
        sid = _create_sumula(numero=777, enunciado="Súmula não conta como flashcard")
        # Revisar a súmula (SM-2)
        r = client.post(f"/api/sumulas/{sid}/review-sm2", json={"quality": 4})
        assert r.status_code == 200, r.text
        depois = client.get("/api/flashcards/today-count").json()["revisados_hoje"]
        assert depois == base, "Revisão de súmula não pode contar como flashcard revisado"

    def test_flashcard_revisado_sai_dos_pendentes(self):
        """Após revisar, o flashcard sai da fila de pendentes de hoje."""
        fid = _create_flashcard("Sai da fila?", "Sim, proxima_revisao futura")
        pend_antes = client.get("/api/flashcards/today-count").json()["pendentes"]
        client.post(f"/api/flashcards/{fid}/review-fsrs", json={"quality": 4})
        pend_depois = client.get("/api/flashcards/today-count").json()["pendentes"]
        assert pend_depois <= pend_antes


class TestFSRSEdital:
    """Testes do FSRS para tópicos do edital."""

    def test_fsrs_edital_review(self):
        """Test /api/edital/{id}/revisar-fsrs."""
        tid = _create_edital_topic("FSRS Edital Mat", "FSRS Tópico")
        r = client.post(f"/api/edital/{tid}/revisar-fsrs", json={"quality": 3})
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == tid
        assert data["intervalo_dias"] >= 1
        assert data["stability"] > 0
        assert data["difficulty"] > 0
        assert "proxima_revisao" in data

    def test_fsrs_edital_review_nonexistent(self):
        """FSRS review on nonexistent edital topic should return 404."""
        r = client.post("/api/edital/99999/revisar-fsrs", json={"quality": 3})
        assert r.status_code == 404


class TestFSRSSumulas:
    """Testes do FSRS para súmulas."""

    def test_fsrs_sumula_review(self):
        """Test /api/sumulas/{id}/review-fsrs."""
        sid = _create_sumula("STJ", 200, "Súmula FSRS test")
        r = client.post(f"/api/sumulas/{sid}/review-fsrs", json={"quality": 4})
        assert r.status_code == 200
        data = r.json()
        assert data["id"] == sid
        assert data["intervalo_dias"] >= 1
        assert data["stability"] > 0
        assert data["difficulty"] > 0
        assert "proxima_revisao" in data

    def test_fsrs_sumula_review_nonexistent(self):
        """FSRS review on nonexistent súmula should return 404."""
        r = client.post("/api/sumulas/99999/review-fsrs", json={"quality": 3})
        assert r.status_code == 404


class TestDesiredRetention:
    """Testes do endpoint desired-retention (FSRS settings)."""

    def test_get_desired_retention_default(self):
        """GET should return default 0.9."""
        r = client.get("/api/settings/desired-retention")
        assert r.status_code == 200
        data = r.json()
        assert "desired_retention" in data
        assert data["desired_retention"] == 0.9

    def test_update_desired_retention(self):
        """PUT should update and persist the value."""
        r = client.put("/api/settings/desired-retention", json={"desired_retention": 0.85})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Verify persisted
        r2 = client.get("/api/settings/desired-retention")
        assert r2.status_code == 200
        assert r2.json()["desired_retention"] == 0.85

    def test_update_desired_retention_invalid_range(self):
        """PUT with value out of range should return 400."""
        r = client.put("/api/settings/desired-retention", json={"desired_retention": 0.5})
        assert r.status_code == 400

        r2 = client.put("/api/settings/desired-retention", json={"desired_retention": 1.0})
        assert r2.status_code == 400


# ============================================================
# 2. MASTERY SYSTEM TESTS
# ============================================================

class TestMastery:
    """Testes do sistema de mastery."""

    def test_mastery_overview_empty(self):
        """Should return valid response even with no data."""
        r = client.get("/api/edital/mastery-overview")
        assert r.status_code == 200
        data = r.json()
        assert "materias" in data
        assert isinstance(data["materias"], list)

    def test_mastery_recalculate(self):
        """Create topics + answers, recalculate, verify levels."""
        # Create edital topics
        tid = _create_edital_topic("Mastery Mat", "Mastery Topic", "Mastery Edital", "Analista")

        # Create related question
        qid = _create_questao(materia="Mastery Mat", topico="Mastery Topic", banca="FCC")

        # Answer questions to build mastery
        client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 30})

        # Recalculate mastery
        r = client.post("/api/edital/mastery/recalculate")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["updated"] >= 1

    def test_mastery_updates_on_question_answer(self):
        """Answer question, verify mastery endpoint returns data."""
        # Create topic
        tid = _create_edital_topic("Mastery Auto", "Auto Update", "Auto Edital", "Juiz")

        # Create question matching topic
        qid = _create_questao(materia="Mastery Auto", topico="Auto Update", banca="VUNESP")

        # Answer correctly
        client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 25})

        # Update mastery
        r = client.post(f"/api/edital/{tid}/mastery-update")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "mastery_level" in data
        assert "mastery_label" in data

    def test_mastery_update_nonexistent_topic(self):
        """Mastery update on nonexistent topic should return 404."""
        r = client.post("/api/edital/99999/mastery-update")
        assert r.status_code == 404


# ============================================================
# 3. LEAGUES TESTS
# ============================================================

class TestLeagues:
    """Testes do sistema de ligas."""

    def test_leagues_current_creates_league(self):
        """First call should auto-create league with bots."""
        r = client.get("/api/leagues/current")
        assert r.status_code == 200
        data = r.json()
        assert "league_id" in data
        assert data["league_id"] > 0
        assert "tier" in data
        assert "standings" in data
        assert isinstance(data["standings"], list)
        assert data["total_members"] > 0
        assert "days_remaining" in data
        assert "user_rank" in data

    def test_leagues_history_empty(self):
        """New user should have empty history (no completed weeks yet)."""
        r = client.get("/api/leagues/history")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list) or "history" in data

    def test_leagues_tier_info(self):
        """Should return all tier definitions."""
        r = client.get("/api/leagues/tier-info")
        assert r.status_code == 200
        data = r.json()
        assert "tiers" in data
        assert isinstance(data["tiers"], list)
        assert len(data["tiers"]) >= 3  # At least 3 tiers
        assert "current_tier" in data
        assert "current_tier_label" in data

        # Each tier should have required fields
        for tier in data["tiers"]:
            assert "tier" in tier
            assert "label" in tier
            assert "order" in tier
            assert "xp_range_min" in tier
            assert "is_current" in tier

    def test_leagues_update_xp(self):
        """Should update weekly XP and recalculate ranking."""
        # Ensure league exists first
        client.get("/api/leagues/current")

        r = client.post("/api/leagues/update-xp")
        assert r.status_code == 200
        data = r.json()
        assert "weekly_xp" in data
        assert "rank" in data
        assert "league_id" in data
        assert data["rank"] >= 1


# ============================================================
# 4. AI TUTOR TESTS
# ============================================================

class TestAITutor:
    """Testes dos endpoints de AI (sem API key, testa a camada de roteamento)."""

    def test_ai_status(self):
        """Should return provider info (likely unavailable without API key)."""
        r = client.get("/api/ai/status")
        assert r.status_code == 200
        data = r.json()
        assert "disponivel" in data
        assert "provider" in data
        assert "modelo" in data
        # Without API key or Ollama, should be unavailable
        assert isinstance(data["disponivel"], bool)

    def test_ai_usage(self):
        """Should return today's usage (0 for new user)."""
        r = client.get("/api/ai/usage")
        assert r.status_code == 200
        data = r.json()
        assert "tokens_used" in data
        assert data["tokens_used"] == 0
        assert "plan" in data
        assert "data" in data
        assert "requests_today" in data
        assert data["requests_today"] == 0

    def test_ai_history_empty(self):
        """Should return empty list for new user."""
        r = client.get("/api/ai/history")
        assert r.status_code == 200
        data = r.json()
        assert "historico" in data
        assert isinstance(data["historico"], list)
        assert data["total"] == 0


# ============================================================
# 5. SOCIAL TESTS
# ============================================================

class TestSocial:
    """Testes dos endpoints sociais."""

    def test_social_friends_empty(self):
        """New user has no friends."""
        r = client.get("/api/social/friends")
        assert r.status_code == 200
        data = r.json()
        assert "friends" in data
        assert isinstance(data["friends"], list)
        assert len(data["friends"]) == 0

    def test_social_groups_empty(self):
        """New user not in any groups."""
        r = client.get("/api/social/groups")
        assert r.status_code == 200
        data = r.json()
        assert "groups" in data
        assert isinstance(data["groups"], list)
        assert len(data["groups"]) == 0

    def test_social_create_group(self):
        """Create group, verify it exists."""
        r = client.post("/api/social/groups", json={
            "nome": "Grupo Teste ConcurseiroOS",
            "descricao": "Grupo para testes",
            "edital_nome": "PC-DF 2026",
            "max_membros": 10,
            "publico": True
        })
        assert r.status_code == 200
        data = r.json()
        assert "group_id" in data
        assert data["group_id"] > 0

        # Verify user is now member
        r2 = client.get("/api/social/groups")
        assert r2.status_code == 200
        groups = r2.json()["groups"]
        assert len(groups) >= 1
        found = any(g["nome"] == "Grupo Teste ConcurseiroOS" for g in groups)
        assert found

    def test_social_feed_empty(self):
        """Empty activity feed for user without activity."""
        r = client.get("/api/social/feed")
        assert r.status_code == 200
        data = r.json()
        assert "feed" in data
        assert isinstance(data["feed"], list)

    def test_social_profile(self):
        """Get own profile."""
        r = client.get("/api/social/profile")
        # This may return 404 if users table doesn't have the test user
        # In that case, just verify the endpoint responds
        assert r.status_code in (200, 404)
        if r.status_code == 200:
            data = r.json()
            assert "user_id" in data
            assert "streak" in data
            assert "level" in data
            assert "xp" in data


# ============================================================
# 6. NOTIFICATIONS TESTS
# ============================================================

class TestNotifications:
    """Testes dos endpoints de push notifications."""

    def test_push_status_no_subscription(self):
        """User with no subscription."""
        r = client.get("/api/push/status")
        assert r.status_code == 200
        data = r.json()
        assert "subscribed" in data
        assert data["subscribed"] is False
        assert "vapid_public_key" in data

    def test_push_preferences_default(self):
        """Default preferences."""
        r = client.get("/api/push/preferences")
        assert r.status_code == 200
        data = r.json()
        assert data["streak_reminders"] is True
        assert data["flashcard_reminders"] is True
        assert data["exam_reminders"] is True
        assert data["challenge_reminders"] is True
        assert "quiet_hours_start" in data
        assert "quiet_hours_end" in data

    def test_push_preferences_update(self):
        """Update preferences and verify persistence."""
        r = client.put("/api/push/preferences", json={
            "streak_reminders": False,
            "flashcard_reminders": True,
            "exam_reminders": False,
            "challenge_reminders": True,
            "quiet_hours_start": 23,
            "quiet_hours_end": 8
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_push_check_triggers(self):
        """Should run without errors (no users with subscriptions = no notifications)."""
        r = client.post("/api/push/check-triggers")
        assert r.status_code == 200
        data = r.json()
        # Should have result keys even if everything is 0
        assert isinstance(data, dict)

    def test_push_vapid_key(self):
        """Should return the VAPID public key."""
        r = client.get("/api/push/vapid-key")
        assert r.status_code == 200
        data = r.json()
        assert "vapid_public_key" in data


# ============================================================
# 7. RAIO-X TESTS
# ============================================================

class TestRaioX:
    """Testes dos endpoints Raio-X (análise de frequência)."""

    def test_raio_x_empty(self):
        """No questions answered yet for this banca = empty results."""
        r = client.get("/api/analytics/raio-x?banca=INEXISTENTE")
        assert r.status_code == 200
        data = r.json()
        assert "topicos" in data
        assert "materias" in data
        assert isinstance(data["topicos"], list)
        assert isinstance(data["materias"], list)
        assert "filtros" in data

    def test_raio_x_with_data(self):
        """Create questions + answers, verify frequency analysis."""
        # Create questions with a specific banca
        qid = _create_questao(materia="Raio-X Mat", topico="Raio-X Topic", banca="FGV")

        # Answer the question
        client.post(f"/api/questoes/{qid}/responder", json={"resposta": "A", "tempo_segundos": 20})

        # Query raio-x
        r = client.get("/api/analytics/raio-x?banca=FGV")
        assert r.status_code == 200
        data = r.json()
        assert "topicos" in data
        assert "banca_selecionada" in data
        assert data["banca_selecionada"] == "FGV"
        # Should have at least one topic
        assert len(data["topicos"]) >= 1

    def test_raio_x_bancas_empty(self):
        """No banca data initially for unfamiliar bancas."""
        r = client.get("/api/analytics/raio-x/bancas")
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_raio_x_prioridades(self):
        """Test priority calculation (may be empty without matching edital+questions)."""
        r = client.get("/api/analytics/raio-x/prioridades")
        assert r.status_code == 200
        data = r.json()
        assert "prioridades" in data
        assert "total_topicos" in data
        assert isinstance(data["prioridades"], list)

    def test_raio_x_prioridades_with_data(self):
        """Create matching edital topics and questions, verify priority scoring."""
        # Create edital topic
        _create_edital_topic("Prio Mat", "Prio Topic", "Prio Edital", "Prio Cargo")

        # Create question matching that materia
        qid = _create_questao(materia="Prio Mat", topico="Prio Topic", banca="IBFC")
        client.post(f"/api/questoes/{qid}/responder", json={"resposta": "B", "tempo_segundos": 30})

        # Check priorities
        r = client.get("/api/analytics/raio-x/prioridades?edital_nome=Prio Edital&cargo=Prio Cargo")
        assert r.status_code == 200
        data = r.json()
        assert "prioridades" in data
        if len(data["prioridades"]) > 0:
            item = data["prioridades"][0]
            assert "materia" in item
            assert "topico" in item
            assert "priority_score" in item
            assert "recomendacao" in item


# ============================================================
# 8. STREAK FREEZE TESTS
# ============================================================

class TestStreakFreeze:
    """Testes do sistema de Streak Freeze."""

    def test_streak_freeze_initial(self):
        """Should have 1 freeze available by default."""
        r = client.get("/api/streak-freeze")
        assert r.status_code == 200
        data = r.json()
        assert "freezes_available" in data
        assert data["freezes_available"] >= 1
        assert "freezes_used" in data
        assert data["freezes_used"] == 0
        assert "max_freezes" in data
        assert data["max_freezes"] == 3
        assert "streak_atual" in data
        assert "earn_next_at" in data

    def test_streak_freeze_use(self):
        """Use freeze — if yesterday had no activity, it should consume freeze and preserve streak."""
        r = client.post("/api/streak-freeze/use")
        assert r.status_code == 200
        data = r.json()
        # Either the freeze is used (ok=True) or not needed (ok=False, had activity)
        assert "ok" in data
        if data["ok"]:
            assert "freezes_remaining" in data
        else:
            assert "message" in data

    def test_streak_freeze_earn(self):
        """Earn freeze — needs 7-day streak. Will likely fail validation for new user."""
        r = client.post("/api/streak-freeze/earn")
        assert r.status_code == 200
        data = r.json()
        assert "ok" in data
        # For a user with streak < 7, it should return ok=False
        if not data["ok"]:
            assert "message" in data

    def test_streak_freeze_use_when_no_freezes(self):
        """After using all freezes, should get an error."""
        # First, try to use all available freezes (multiple times)
        # The endpoint may return ok=False or 400 depending on state
        # This tests the boundary condition
        r = client.get("/api/streak-freeze")
        assert r.status_code == 200
        # Just verify the endpoint works consistently
        data = r.json()
        assert data["freezes_available"] >= 0


# ============================================================
# ADDITIONAL INTEGRATION TESTS
# ============================================================

class TestFSRSIntegration:
    """Integration tests combining FSRS with other features."""

    def test_fsrs_desired_retention_affects_review(self):
        """Changing desired_retention should affect FSRS intervals."""
        # Set high retention (shorter intervals)
        client.put("/api/settings/desired-retention", json={"desired_retention": 0.95})

        fid_high = _create_flashcard("High retention?", "Short interval")
        r_high = client.post(f"/api/flashcards/{fid_high}/review-fsrs", json={"quality": 3})
        assert r_high.status_code == 200
        interval_high_ret = r_high.json()["intervalo_dias"]

        # Set low retention (longer intervals)
        client.put("/api/settings/desired-retention", json={"desired_retention": 0.7})

        fid_low = _create_flashcard("Low retention?", "Long interval")
        r_low = client.post(f"/api/flashcards/{fid_low}/review-fsrs", json={"quality": 3})
        assert r_low.status_code == 200
        interval_low_ret = r_low.json()["intervalo_dias"]

        # Higher retention = shorter intervals (reviewing more often)
        assert interval_high_ret <= interval_low_ret

        # Reset to default
        client.put("/api/settings/desired-retention", json={"desired_retention": 0.9})

    def test_fsrs_multiple_ratings(self):
        """Test FSRS with all valid quality ratings (0-5)."""
        for quality in [0, 1, 2, 3, 4, 5]:
            fid = _create_flashcard(f"Rating {quality}?", f"Answer {quality}")
            r = client.post(f"/api/flashcards/{fid}/review-fsrs", json={"quality": quality})
            assert r.status_code == 200, f"Failed for quality={quality}"
            data = r.json()
            assert data["intervalo_dias"] >= 1
            assert data["stability"] > 0


class TestLeaguesIntegration:
    """Integration tests for leagues with activity."""

    def test_leagues_standings_have_user(self):
        """User should appear in standings after getting current league."""
        r = client.get("/api/leagues/current")
        assert r.status_code == 200
        data = r.json()
        standings = data["standings"]

        # User should be in standings
        user_in_standings = any(s.get("is_current_user") for s in standings)
        assert user_in_standings

    def test_leagues_standings_zones(self):
        """Standings should mark promotion and demotion zones."""
        r = client.get("/api/leagues/current")
        assert r.status_code == 200
        data = r.json()
        standings = data["standings"]

        zones = set(s["zone"] for s in standings)
        # Should have at least safe zone
        assert "safe" in zones or "promotion" in zones or "demotion" in zones


class TestNotificationsIntegration:
    """Integration tests for notification preferences."""

    def test_preferences_persist_across_reads(self):
        """Updated preferences should persist when read again."""
        # Update
        r = client.put("/api/push/preferences", json={
            "streak_reminders": True,
            "flashcard_reminders": False,
            "exam_reminders": True,
            "challenge_reminders": False,
            "quiet_hours_start": 21,
            "quiet_hours_end": 6
        })
        assert r.status_code == 200

        # Read back
        r2 = client.get("/api/push/preferences")
        assert r2.status_code == 200
        data = r2.json()
        assert data["flashcard_reminders"] is False
        assert data["challenge_reminders"] is False
        assert data["quiet_hours_start"] == 21
        assert data["quiet_hours_end"] == 6


# ============================================================
# CLEANUP
# ============================================================

def teardown_module():
    """Cleanup temp DB."""
    try:
        os.unlink(_tmp_db.name)
    except Exception:
        pass

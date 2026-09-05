"""Testes da classificação de rate limit por endpoint (rate_limit.classify_endpoint)."""
import os
import sys

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rate_limit import classify_endpoint

from settings import settings


def test_auth_sensivel_usa_limite_estrito():
    for p in ("/api/auth/login", "/api/auth/register", "/api/auth/verify-code", "/api/auth/refresh"):
        etype, limit = classify_endpoint(p)
        assert etype == "auth"
        assert limit == settings.RATE_LIMIT_AUTH


def test_auth_leitura_usa_limite_geral():
    # Endpoints chamados a cada page load NÃO podem usar o bucket estrito.
    for p in ("/api/auth/status", "/api/auth/me", "/api/auth/plans",
              "/api/auth/my-plan", "/api/auth/creditos", "/api/auth/vitalicio-status"):
        etype, limit = classify_endpoint(p)
        assert etype == "general", f"{p} deveria ser 'general', veio '{etype}'"
        assert limit == settings.RATE_LIMIT_GENERAL


def test_ai_tutor_usa_limite_ia():
    etype, limit = classify_endpoint("/api/ai-tutor/chat")
    assert etype == "ai_tutor"
    assert limit == settings.RATE_LIMIT_AI


def test_endpoint_generico():
    etype, limit = classify_endpoint("/api/dashboard")
    assert etype == "general"
    assert limit == settings.RATE_LIMIT_GENERAL

"""
Testes do tradutor de erros de provedores de IA (_traduzir_erro_provedor).

Garante que erros HTTP dos provedores (GLM/Zhipu, OpenAI, etc.) sejam
convertidos em mensagens claras em pt-BR com o status HTTP adequado, em vez de
um 502 genérico que escondia a causa real (ex.: saldo insuficiente).

Executar: pytest tests/test_ai_erro_provedor.py -v
"""
import os
import sys

os.environ["AUTH_ENABLED"] = "false"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.ai_tutor import _traduzir_erro_provedor


def test_saldo_insuficiente_glm_1113():
    """GLM code 1113 (余额不足) → 402 com mensagem de recarga."""
    corpo = '{"error":{"code":"1113","message":"余额不足或无可用资源包,请充值。"}}'
    status, msg = _traduzir_erro_provedor("glm", 429, corpo)
    assert status == 402
    assert "saldo insuficiente" in msg.lower()
    assert "GLM" in msg


def test_modelo_inexistente_glm_1211():
    """GLM code 1211 (模型不存在) → 400 orientando corrigir o modelo."""
    corpo = '{"error":{"code":"1211","message":"模型不存在，请检查模型代码。"}}'
    status, msg = _traduzir_erro_provedor("glm", 400, corpo)
    assert status == 400
    assert "modelo" in msg.lower()
    assert "glm-4.5-flash" in msg


def test_api_key_invalida():
    """401/403 → 401 com mensagem de key inválida."""
    corpo = '{"error":{"message":"Invalid API key provided"}}'
    status, msg = _traduzir_erro_provedor("openai", 401, corpo)
    assert status == 401
    assert "api key" in msg.lower()


def test_rate_limit_sem_saldo():
    """429 sem indício de saldo → 429 (rate limit)."""
    corpo = '{"error":{"message":"Rate limit exceeded, please slow down"}}'
    status, msg = _traduzir_erro_provedor("openai", 429, corpo)
    assert status == 429
    assert "rate limit" in msg.lower()


def test_fallback_repassa_mensagem_do_provedor():
    """Erro desconhecido com mensagem → 502 repassando a mensagem do provedor."""
    corpo = '{"error":{"message":"Some unexpected provider error"}}'
    status, msg = _traduzir_erro_provedor("mistral", 500, corpo)
    assert status == 502
    assert "Some unexpected provider error" in msg


def test_fallback_corpo_nao_json():
    """Corpo não-JSON → 502 com o status (sem quebrar)."""
    corpo = "<html>502 Bad Gateway</html>"
    status, msg = _traduzir_erro_provedor("grok", 502, corpo)
    assert status == 502
    assert "grok" in msg.lower()


def test_insufficient_balance_em_ingles():
    """Provedor que reporta 'insufficient balance' em inglês → 402."""
    corpo = '{"error":{"message":"Insufficient balance to complete request"}}'
    status, msg = _traduzir_erro_provedor("deepseek", 402, corpo)
    assert status == 402
    assert "saldo insuficiente" in msg.lower()

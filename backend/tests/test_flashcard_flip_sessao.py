"""Regressão: sessões avulsas de flashcard (Risco de Esquecimento por-IDs,
disciplina, aleatório) devem usar o MESMO mecanismo de flip 3D da revisão de
hoje (showCurrentFlashcard), e não a UI antiga/plana.

Como o projeto não tem runner JS, validamos estaticamente o código-fonte de
frontend/js/modules/flashcards.js. Estas asserções travam a regressão descrita:
"ao chamar os flashcards da aba do treinador, a tela ainda era a antiga, sem a
animação 3D" — porque o caminho por-IDs renderiza via showSessaoFlashcard().

Complementa test_endpoints.py::test_flashcards_por_ids_* (backend do caminho).
"""
import re
from pathlib import Path

import pytest

FLASH_JS = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "js" / "modules" / "flashcards.js"
)
SW_JS = Path(__file__).resolve().parents[2] / "frontend" / "sw.js"


@pytest.fixture(scope="module")
def src() -> str:
    return FLASH_JS.read_text(encoding="utf-8")


def _extrair_funcao(src: str, header: str) -> str:
    """Extrai o corpo de uma função pelo balanceamento de chaves a partir do
    cabeçalho informado (ex.: 'function showSessaoFlashcard()')."""
    idx = src.index(header)
    abre = src.index("{", idx)
    profundidade = 0
    for i in range(abre, len(src)):
        c = src[i]
        if c == "{":
            profundidade += 1
        elif c == "}":
            profundidade -= 1
            if profundidade == 0:
                return src[abre : i + 1]
    raise AssertionError(f"não fechou chaves para {header!r}")


def test_arquivo_existe(src):
    assert "showSessaoFlashcard" in src


def test_sessao_ativa_flip_mode(src):
    """showSessaoFlashcard deve ativar a classe flip-mode no #flash-card-area
    (o mesmo toggle de showCurrentFlashcard) — sem isso a carta não gira em 3D."""
    corpo = _extrair_funcao(src, "function showSessaoFlashcard()")
    assert "getElementById('flash-card-area')" in corpo, (
        "showSessaoFlashcard não referencia mais o #flash-card-area (flip 3D)"
    )
    assert re.search(
        r"classList\.toggle\(\s*'flip-mode'\s*,\s*_flipMode\s*&&\s*!_examMode\s*\)",
        corpo,
    ), "showSessaoFlashcard não ativa flip-mode como showCurrentFlashcard"
    # Reseta o estado da carta ao trocar de card (frente).
    assert "classList.remove('flipped')" in corpo
    assert "_isFlipped = false" in corpo


def test_sessao_nao_usa_reveal_plano_inline(src):
    """A UI antiga revelava com um onclick inline montando os botões dentro de
    showSessaoFlashcard. Agora o reveal é delegado a _revealSessaoAnswer."""
    corpo = _extrair_funcao(src, "function showSessaoFlashcard()")
    assert "rb.onclick = _revealSessaoAnswer" in corpo, (
        "o botão de revelar da sessão deve delegar a _revealSessaoAnswer"
    )
    # Não pode ter voltado a montar os botões de sessaoNext inline no onclick.
    assert corpo.count("sessaoNext(") == 0, (
        "showSessaoFlashcard não deve montar os botões de avaliação inline "
        "(isso é responsabilidade de _revealSessaoAnswer)"
    )


def test_reveal_sessao_dispara_sessaonext(src):
    """_revealSessaoAnswer revela a resposta e monta os 6 botões que chamam
    sessaoNext(0..5) — mesmo fluxo FSRS da sessão."""
    assert "function _revealSessaoAnswer()" in src
    corpo = _extrair_funcao(src, "function _revealSessaoAnswer()")
    for q in range(6):
        assert f"sessaoNext({q})" in corpo, f"falta botão sessaoNext({q})"
    assert "getElementById('flash-answer')" in corpo


def test_flipcard_roteia_para_sessao(src):
    """flipCard() deve escolher o reveal da sessão quando há sessão ativa,
    senão o reveal do fluxo de hoje (revealAnswer)."""
    corpo = _extrair_funcao(src, "function flipCard()")
    assert "_sessaoAtiva()" in corpo, "flipCard não checa sessão ativa"
    assert "_revealSessaoAnswer" in corpo and "revealAnswer" in corpo, (
        "flipCard deve rotear entre _revealSessaoAnswer e revealAnswer"
    )


def test_sessao_ativa_helper_existe(src):
    """_sessaoAtiva() define 'há sessão em andamento' com base em
    flashSessaoMode e no índice dentro da fila."""
    assert "function _sessaoAtiva()" in src
    corpo = _extrair_funcao(src, "function _sessaoAtiva()")
    assert "flashSessaoMode" in corpo
    assert "flashSessaoIndex < flashSessao.length" in corpo


def test_fim_de_sessao_desvira_carta(src):
    """Ao concluir a sessão, a carta é desvirada e sai do flip para a mensagem
    de conclusão aparecer na face frontal (não no verso girado)."""
    corpo = _extrair_funcao(src, "function showSessaoFlashcard()")
    trecho_fim = corpo[: corpo.index("Sessão concluída")]
    assert "classList.remove('flipped')" in trecho_fim
    assert "Parabéns" in corpo


def test_sw_cache_version_incrementada():
    """Regra do projeto: alterar JS precached exige bump de CACHE_VERSION.
    flashcards.js está em PRECACHE_URLS, então a versão não pode ser 'v2'."""
    sw = SW_JS.read_text(encoding="utf-8")
    assert "/js/modules/flashcards.js" in sw
    m = re.search(r"const CACHE_VERSION = '(v\d+)'", sw)
    assert m, "CACHE_VERSION não encontrada em sw.js"
    versao = int(m.group(1)[1:])
    assert versao >= 3, f"CACHE_VERSION deve ter sido incrementada (achou {m.group(1)})"

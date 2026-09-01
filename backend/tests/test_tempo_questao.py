"""Testes da função de tempo adaptativo por questão (calcular_tempo_resposta_questao).

Garante que o cálculo é mais justo que o antigo:
- inclui o texto das alternativas (não só o enunciado);
- aplica fator por dificuldade;
- respeita a faixa mínimo/máximo;
- questões mais longas recebem mais tempo.

Executar: pytest tests/test_tempo_questao.py -v --no-cov
"""
import os
import sys

os.environ.setdefault("AUTH_ENABLED", "false")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import calcular_tempo_resposta_questao as calc


_ENUNCIADO_CURTO = "O servidor estável perde o cargo por sentença transitada em julgado."


def test_alternativas_longas_aumentam_o_tempo():
    """Alternativas com muito texto devem elevar o tempo (o cálculo antigo ignorava isso)."""
    alts_curtas = ["Certo", "Errado"]
    alts_longas = [" ".join(["palavra"] * 30) for _ in range(5)]
    t_curto = calc(_ENUNCIADO_CURTO, alts_curtas, "Médio")
    t_longo = calc(_ENUNCIADO_CURTO, alts_longas, "Médio")
    assert t_longo > t_curto


def test_fator_dificuldade_ordena_tempos():
    """Difícil > Médio > Fácil para a mesma questão."""
    alts = [" ".join(["op"] * 10) for _ in range(5)]
    t_facil = calc(_ENUNCIADO_CURTO, alts, "Fácil")
    t_medio = calc(_ENUNCIADO_CURTO, alts, "Médio")
    t_dificil = calc(_ENUNCIADO_CURTO, alts, "Difícil")
    assert t_facil <= t_medio <= t_dificil
    # E há diferença real entre extremos (fora de clamp).
    assert t_dificil > t_facil


def test_respeita_faixa_minimo_maximo():
    """Tempo fica dentro de [minimo, maximo] mesmo em extremos."""
    # Questão minúscula → não abaixo do mínimo.
    t_min = calc("Sim?", ["a", "b"], "Fácil", minimo=30, maximo=180)
    assert t_min >= 30
    # Questão gigante → não acima do máximo.
    enorme = " ".join(["palavra"] * 2000)
    t_max = calc(enorme, [enorme] * 5, "Difícil", minimo=30, maximo=180)
    assert t_max <= 180


def test_dificuldade_desconhecida_usa_medio():
    """Rótulo de dificuldade inesperado cai no fator médio (não quebra)."""
    alts = [" ".join(["op"] * 10) for _ in range(5)]
    t_desc = calc(_ENUNCIADO_CURTO, alts, "Sei lá")
    t_medio = calc(_ENUNCIADO_CURTO, alts, "Médio")
    assert t_desc == t_medio


def test_aceita_alternativas_como_dicts():
    """Aceita lista de dicts {'texto': ...} além de lista de strings."""
    alts_str = [" ".join(["x"] * 12) for _ in range(4)]
    alts_dict = [{"texto": " ".join(["x"] * 12)} for _ in range(4)]
    assert calc(_ENUNCIADO_CURTO, alts_str, "Médio") == calc(_ENUNCIADO_CURTO, alts_dict, "Médio")


def test_mais_justo_que_o_antigo_em_questao_media():
    """Questão média com 5 alternativas: o novo cálculo dá mais tempo que o antigo (~24s)."""
    def antigo(enunciado, n_alt):
        palavras = len(enunciado.split()) if enunciado else 10
        return max(20, min(90, int((palavras / 200) * 60 + n_alt * 3 + 5)))

    enunciado = "Assinale a alternativa correta sobre os princípios da administração pública do art. 37 da CF."
    alts = [
        "A administração deve obedecer apenas à legalidade e eficiência.",
        "Os princípios são legalidade, impessoalidade, moralidade, publicidade e eficiência.",
        "A moralidade não é princípio expresso na Constituição Federal de 1988.",
        "A eficiência foi incluída pela EC 19/1998 e é princípio expresso.",
        "Publicidade e eficiência são sinônimos no texto constitucional vigente.",
    ]
    t_novo = calc(enunciado, alts, "Médio")
    t_antigo = antigo(enunciado, len(alts))
    assert t_novo > t_antigo

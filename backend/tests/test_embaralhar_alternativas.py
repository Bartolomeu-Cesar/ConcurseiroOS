"""Testes de _embaralhar_alternativas: embaralha a ordem visual das alternativas
preservando o gabarito (recalcula resposta_correta para a nova posição)."""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.questoes.core import _embaralhar_alternativas  # noqa: E402

_Q4 = {
    "id": 42,
    "alternativa_a": "Texto A (CORRETA)",
    "alternativa_b": "Texto B",
    "alternativa_c": "Texto C",
    "alternativa_d": "Texto D",
    "alternativa_e": "",
    "resposta_correta": "A",
}


class TestEmbaralharAlternativas:
    def test_preserva_gabarito_4_alternativas(self):
        for uid in range(1, 20):
            r = _embaralhar_alternativas(copy.deepcopy(_Q4), uid)
            nova = r["resposta_correta"]
            # O texto na nova posição correta deve ser o texto originalmente correto.
            assert r[f"alternativa_{nova.lower()}"] == "Texto A (CORRETA)", f"user {uid}"

    def test_preserva_gabarito_5_alternativas(self):
        q5 = dict(_Q4, alternativa_e="Texto E", resposta_correta="C")
        for uid in range(1, 20):
            r = _embaralhar_alternativas(copy.deepcopy(q5), uid)
            nova = r["resposta_correta"]
            assert r[f"alternativa_{nova.lower()}"] == "Texto C", f"user {uid}"

    def test_deterministico_por_usuario(self):
        r1 = _embaralhar_alternativas(copy.deepcopy(_Q4), 5)
        r2 = _embaralhar_alternativas(copy.deepcopy(_Q4), 5)
        assert r1["mapeamento"] == r2["mapeamento"]

    def test_certo_errado_nao_embaralha(self):
        ce = {
            "id": 7, "alternativa_a": "CERTO", "alternativa_b": "ERRADO",
            "alternativa_c": "", "alternativa_d": "", "alternativa_e": "",
            "resposta_correta": "A",
        }
        r = _embaralhar_alternativas(ce, 1)
        assert r["embaralhada"] is False
        assert r["resposta_correta"] == "A"

    def test_mapeamento_traduz_letra_visual_para_original(self):
        r = _embaralhar_alternativas(copy.deepcopy(_Q4), 1)
        # mapeamento: nova_letra -> letra_original; a letra correta visual deve
        # mapear para 'A' (a original correta).
        assert r["mapeamento"][r["resposta_correta"]] == "A"

    def test_nao_lanca_para_4_alternativas(self):
        # Regressão: antes lançava IndexError na limpeza de alternativas extras.
        r = _embaralhar_alternativas(copy.deepcopy(_Q4), 1)
        assert r["alternativa_e"] == ""

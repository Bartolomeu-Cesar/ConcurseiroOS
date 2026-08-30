"""Testes de captura e aplicação de gabarito na importação de questões.

Cobre:
- _parse_gabarito: formatos de grade, rotulados por questão e inline sequenciais.
- _aplicar_gabarito_no_texto: gabarito no FINAL do mesmo PDF, inclusive quando o
  parser (ex.: Estratégia) não lê gabarito por conta própria.
- _aplicar_gabarito_externo: gabarito de ARQUIVO SEPARADO, por número e por ordem.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.questoes.importacao import (  # noqa: E402
    _aplicar_gabarito_externo,
    _aplicar_gabarito_no_texto,
    _parse_gabarito,
    _parse_questoes_texto,
)


class TestParseGabaritoFormatos:
    def test_grade_cespe_numeros_e_letras(self):
        g = _parse_gabarito("1 2 3 4 5\nC E C E C")
        assert g == {1: "C", 2: "E", 3: "C", 4: "E", 5: "C"}

    def test_tradicional_hifen(self):
        g = _parse_gabarito("1-C\n2-E\n3-C\n4-E\n5-C")
        assert g == {1: "C", 2: "E", 3: "C", 4: "E", 5: "C"}

    def test_dois_pontos(self):
        g = _parse_gabarito("Gabarito\n1: A\n2: B\n3: C\n4: D\n5: E")
        assert g == {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}

    def test_parenteses(self):
        g = _parse_gabarito("1) A\n2) B\n3) C\n4) D\n5) E")
        assert g == {1: "A", 2: "B", 3: "C", 4: "D", 5: "E"}

    def test_pipe(self):
        g = _parse_gabarito("1 | A\n2 | B\n3 | C\n4 | D")
        assert {1: "A", 2: "B", 3: "C", 4: "D"}.items() <= g.items()

    # --- Formatos que ANTES falhavam ---
    def test_questao_n_letra_x(self):
        g = _parse_gabarito("Questão 1: Letra A\nQuestão 2: Letra B\nQuestão 3: Letra C")
        assert g == {1: "A", 2: "B", 3: "C"}

    def test_n_hifen_letra_x(self):
        g = _parse_gabarito("1 - Letra A\n2 - Letra B\n3 - Letra C")
        assert g == {1: "A", 2: "B", 3: "C"}

    def test_resposta_correta_inline_sem_numero(self):
        g = _parse_gabarito("Resposta correta: A\nResposta correta: B\nResposta correta: C")
        assert g == {1: "A", 2: "B", 3: "C"}

    def test_gabarito_label_inline_sem_numero(self):
        g = _parse_gabarito("Gabarito: A\nGabarito: B\nGabarito: E")
        assert g == {1: "A", 2: "B", 3: "E"}

    def test_resposta_inline_sem_numero(self):
        g = _parse_gabarito("Resposta: A\nResposta: B\nResposta: E\nResposta: D")
        assert g == {1: "A", 2: "B", 3: "E", 4: "D"}

    def test_bloco_respostas_linhas_alternadas_estrategia(self):
        """Formato do Estratégia: seção 'Respostas:' com número e letra em
        linhas separadas (num\\nletra\\nnum\\nletra...)."""
        texto = (
            "...corpo das questões com A B C D E e números soltos 1 2 3...\n"
            "Essa questão possui comentário do professor no site\n"
            "4001505070\n"
            "Respostas:\n"
            "1\nA\n2\nD\n3\nE\n4\nC\n5\nB\n6\nB\n7\nA\n8\nA\n"
        )
        g = _parse_gabarito(texto)
        assert g[1] == "A"
        assert g[2] == "D"
        assert g[3] == "E"
        assert g[4] == "C"
        assert g[5] == "B"
        assert g[8] == "A"
        assert len(g) == 8

    def test_bloco_respostas_ignora_ruido_do_corpo(self):
        """Números e letras soltos no corpo NÃO devem poluir o gabarito quando
        existe uma seção 'Respostas:' explícita."""
        texto = (
            "Questão 1\nA\ntexto alternativa\nB\noutro texto\n"
            "Respostas:\n1\nC\n2\nD\n3\nE\n4\nA\n"
        )
        g = _parse_gabarito(texto)
        # deve refletir o bloco Respostas, não o corpo
        assert g[1] == "C"
        assert g[2] == "D"
        assert g[3] == "E"
        assert g[4] == "A"


class TestAplicarGabaritoNoTexto:
    def test_estrategia_com_gabarito_no_final(self):
        """Formato Estratégia (que não lê gabarito) deve aproveitar o gabarito
        presente no final do MESMO PDF via aplicação central."""
        texto = """
Questão 1
2024
FCC
Assinale a alternativa correta sobre concordância verbal.
A
Primeira opção incorreta aqui.
B
Segunda opção também incorreta.
C
Terceira opção correta de fato.
D
Quarta opção incorreta.
E
Quinta opção incorreta.
Essa questão possui comentário do professor no site
40019
Questão 2
2024
FCC
Assinale a alternativa que apresenta regência correta.
A
Alternativa A da questão dois.
B
Alternativa B correta da dois.
C
Alternativa C incorreta.
D
Alternativa D incorreta.
E
Alternativa E incorreta.
Essa questão possui comentário do professor no site
40020

GABARITO
1 C
2 B
"""
        qs = _parse_questoes_texto(texto, materia="Português")
        assert len(qs) == 2
        respostas = {q["numero"]: q["resposta_correta"] for q in qs}
        assert respostas[1] == "C"
        assert respostas[2] == "B"

    def test_nao_sobrescreve_resposta_existente(self):
        qs = [
            {"numero": 1, "resposta_correta": "D", "tipo": "multipla"},
            {"numero": 2, "resposta_correta": "", "tipo": "multipla"},
        ]
        _aplicar_gabarito_no_texto(qs, "1) A\n2) B\n3) C")
        # q1 mantém 'D' (não sobrescreve); q2 recebe 'B'
        assert qs[0]["resposta_correta"] == "D"
        assert qs[1]["resposta_correta"] == "B"

    def test_certo_errado_converte_c_e_para_a_b(self):
        qs = [
            {"numero": 1, "resposta_correta": "", "tipo": "certo_errado"},
            {"numero": 2, "resposta_correta": "", "tipo": "certo_errado"},
            {"numero": 3, "resposta_correta": "", "tipo": "certo_errado"},
        ]
        _aplicar_gabarito_no_texto(qs, "1-C\n2-E\n3-C")
        assert qs[0]["resposta_correta"] == "A"  # Certo -> A
        assert qs[1]["resposta_correta"] == "B"  # Errado -> B
        assert qs[2]["resposta_correta"] == "A"  # Certo -> A


class TestAplicarGabaritoExterno:
    def test_por_numero(self):
        qs = [
            {"numero": 1, "resposta_correta": "", "tipo": "multipla"},
            {"numero": 2, "resposta_correta": "", "tipo": "multipla"},
        ]
        _aplicar_gabarito_externo(qs, {1: "A", 2: "B"})
        assert qs[0]["resposta_correta"] == "A"
        assert qs[1]["resposta_correta"] == "B"

    def test_fallback_por_ordem_quando_numeracao_nao_bate(self):
        qs = [
            {"numero": 1, "resposta_correta": "", "tipo": "multipla"},
            {"numero": 2, "resposta_correta": "", "tipo": "multipla"},
            {"numero": 3, "resposta_correta": "", "tipo": "certo_errado"},
        ]
        # Gabarito com numeração deslocada -> deve casar por ordem
        _aplicar_gabarito_externo(qs, {101: "A", 102: "D", 103: "C"})
        assert qs[0]["resposta_correta"] == "A"
        assert qs[1]["resposta_correta"] == "D"
        assert qs[2]["resposta_correta"] == "A"  # 'C' (certo) -> A

    def test_gabarito_vazio_nao_altera(self):
        qs = [{"numero": 1, "resposta_correta": "", "tipo": "multipla"}]
        _aplicar_gabarito_externo(qs, {})
        assert qs[0]["resposta_correta"] == ""

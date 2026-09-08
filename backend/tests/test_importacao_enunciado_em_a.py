"""Regressão: parser de importação QConcursos não deve confundir o "A " inicial
de um enunciado (artigo maiúsculo: "A sociedade...", "A Unidade...", "A fim de...")
com o rótulo da alternativa A.

Bug original: o resto do enunciado ia para `alternativa_a` e as alternativas
reais eram deslocadas (b→a, c→b, ...), deixando a questão sem gabarito utilizável.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routers.questoes.importacao import _parse_qconcursos


def _q(texto):
    qs = _parse_qconcursos(texto)
    assert qs, "nenhuma questão extraída"
    return qs[0]


def test_enunciado_comecando_por_A_nao_vira_alternativa():
    texto = """Ano: 2024 Banca: FGV Órgão: CM Fortaleza
A Unidade Central de Processamento (UCP) é um importante componente de um computador. É correto afirmar que a UCP
B é responsável por executar instruções de um programa de computador.
C é um dispositivo periférico apenas de entrada de dados.
D é um dispositivo periférico de entrada e saída de dados.
E é o gabinete que armazena os componentes do computador.
"""
    q = _q(texto)
    # O enunciado deve conter o texto completo, incluindo o "A Unidade..." inicial.
    assert "Unidade Central de Processamento" in q["enunciado"]
    assert "É correto afirmar que a UCP" in q["enunciado"]
    # As alternativas reais (antes rotuladas B–E) viram A–D.
    assert q["alternativa_a"].startswith("é responsável por executar")
    assert q["alternativa_b"].startswith("é um dispositivo periférico apenas")
    assert q["alternativa_c"].startswith("é um dispositivo periférico de entrada e saída")
    assert q["alternativa_d"].startswith("é o gabinete")
    assert q["alternativa_e"] == ""


def test_enunciado_comecando_por_A_fim_de():
    texto = """Ano: 2024 Banca: CESPE Órgão: SEFAZ AC
A fim de facilitar a leitura para pessoa com deficiência, o Microsoft Word 365 disponibiliza o recurso denominado
B Verificar Acessibilidade.
C Editor.
D Traduzir.
E Previsões de Texto.
"""
    q = _q(texto)
    assert "fim de facilitar a leitura" in q["enunciado"]
    assert q["alternativa_a"] == "Verificar Acessibilidade."
    assert q["alternativa_b"] == "Editor."
    assert q["alternativa_c"] == "Traduzir."
    assert q["alternativa_d"] == "Previsões de Texto."


def test_questao_normal_nao_e_afetada():
    """Questão cujo enunciado NÃO começa por 'A ' deve continuar com 5 alternativas."""
    texto = """Ano: 2024 Banca: CESPE Órgão: SEFAZ AC
O código malicioso que executa funções maliciosas sem o conhecimento do usuário é denominado
A ransomware.
B spyware.
C trojan.
D stalkerware.
E vírus.
"""
    q = _q(texto)
    assert q["enunciado"].startswith("O código malicioso")
    assert q["alternativa_a"] == "ransomware."
    assert q["alternativa_b"] == "spyware."
    assert q["alternativa_c"] == "trojan."
    assert q["alternativa_d"] == "stalkerware."
    assert q["alternativa_e"] == "vírus."


def test_alternativa_A_curta_legitima_nao_reancorada():
    """Se a alternativa A é curta (alternativa real, não enunciado), não reancorar.
    Ex.: enunciado curto + alternativas curtas iniciando em A."""
    texto = """Ano: 2024 Banca: VUNESP Órgão: TJ SP
Assinale a alternativa correta sobre backup.
A completo.
B incremental.
C diferencial.
D espelhado.
E sintético.
"""
    q = _q(texto)
    assert q["enunciado"].startswith("Assinale a alternativa correta")
    assert q["alternativa_a"] == "completo."
    assert q["alternativa_e"] == "sintético."

"""Teste de regressão do parser de questões CESPE/CEBRASPE (múltipla escolha A–E).

Baseado numa prova real baixada do PCI Concursos (SSP/MA — Polícia Civil,
Cargo 5: Perito Criminal, aplicação 28/1/2018), caderno CG4 (Q1-20) + 005
(Q21-60), 60 questões objetivas A–E.

Cobre os bugs corrigidos:
- Roteamento: _is_cespe_format dava True e mandava ao parser Certo/Errado, que
  retornava 0 questões (a prova é múltipla escolha). Agora _is_cespe_multipla_format
  tem prioridade.
- Ruído do PCI (marca-d'água pcimarkpci, URLs, cabeçalhos ||...||, linhas
  CESPE|CEBRASPE) é removido antes do parsing.
- Falso-positivo do "A" inicial de enunciado ("A pontuação...", "A presença...")
  sendo confundido com a alternativa A — resolvido pela ancoragem na melhor
  progressão A→E.
- Marcador "QUESTÃO N" colado a caractere de ruído ("0QUESTÃO 42").
- Alternativas gráficas (figuras): letra sozinha, texto vazio (Q23-25).
- Gabarito NÃO é extraído do corpo da prova (evita falsos positivos); vem do
  arquivo/texto separado. Validação por número + anulação (X).

O gabarito verdadeiro (ORÁCULO) foi lido diretamente das imagens da grade
oficial do gabarito (fonte de verdade).

Executar: pytest tests/test_parser_pci.py -v
"""

import os
import sys
import tempfile

_tmp_db = tempfile.NamedTemporaryFile(suffix="_pci.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

database.DB_PATH = _tmp_db.name
database.init_db()

from routers.questoes.importacao import (
    _aplicar_gabarito_externo,
    _is_cespe_multipla_format,
    _limpar_ruido_pci,
    _parse_cespe_multipla,
    _parse_questoes_texto,
)

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "pci_prova_cespe.txt")


def _texto_prova() -> str:
    with open(_FIXTURE, encoding="utf-8") as f:
        return f.read()


# Gabarito VERDADEIRO (oráculo) lido das imagens da grade oficial:
#   CG4  (Q1-20):  B D E A D E C B B A D E X E C A C X X X
#   005  (Q21-40): B A B B B C D B E D A D A A D E B C D A
#   005  (Q41-60): B D B C B B D D A A B E E B A A X D D A
_GABARITO_VERDADEIRO: dict[int, str] = {}
for _i, _l in enumerate("BDEADECBBADEXECACXXX"):
    _GABARITO_VERDADEIRO[_i + 1] = _l
for _i, _l in enumerate("BABBBCDBEDADAADEBCDA"):
    _GABARITO_VERDADEIRO[_i + 21] = _l
for _i, _l in enumerate("BDBCBBDDAABEEBAAXDDA"):
    _GABARITO_VERDADEIRO[_i + 41] = _l

# Questões anuladas (X) — não recebem resposta.
_ANULADAS = {n for n, l in _GABARITO_VERDADEIRO.items() if l == "X"}
# Alternativas gráficas (figuras): sem texto nas alternativas.
_GRAFICAS = {23, 24, 25}


def test_limpar_ruido_pci_remove_marca_e_cabecalhos():
    """A pré-limpeza remove marca-d'água, URL, cabeçalhos e isola QUESTÃO N."""
    txt = _texto_prova()
    limpo = _limpar_ruido_pci(txt)
    assert "pcimarkpci" not in limpo
    assert "www.pciconcursos.com.br" not in limpo
    assert "||373_SSPMA" not in limpo
    # cabeçalho institucional CESPE | CEBRASPE removido
    assert "CESPE | CEBRASPE" not in limpo
    # marcador colado "0QUESTÃO 42" foi isolado com quebra de linha
    assert "0QUESTÃO 42" not in limpo


def test_detecta_formato_cespe_multipla():
    assert _is_cespe_multipla_format(_texto_prova()) is True


def test_extrai_todas_as_60_questoes():
    qs = _parse_questoes_texto(_texto_prova(), materia="", banca="CESPE")
    nums = sorted(q["numero"] for q in qs)
    assert len(qs) == 60, f"esperado 60, veio {len(qs)}"
    assert nums == list(range(1, 61)), f"faltando/duplicado: {nums}"


def test_nao_ha_duplicatas():
    qs = _parse_questoes_texto(_texto_prova(), materia="", banca="CESPE")
    nums = [q["numero"] for q in qs]
    assert len(nums) == len(set(nums)), "há questões duplicadas"


def test_questoes_texto_tem_4_ou_5_alternativas():
    """Questões textuais têm >=4 alternativas; as gráficas ficam vazias."""
    qs = {q["numero"]: q for q in _parse_questoes_texto(_texto_prova(), banca="CESPE")}
    for n, q in qs.items():
        alts = [q["alternativa_a"], q["alternativa_b"], q["alternativa_c"], q["alternativa_d"], q["alternativa_e"]]
        preenchidas = sum(1 for a in alts if a)
        if n in _GRAFICAS:
            assert preenchidas == 0, f"Q{n} deveria ser gráfica (alts vazias)"
        else:
            assert preenchidas >= 4, f"Q{n} tem só {preenchidas} alternativas"


def test_enunciados_nao_vazios():
    qs = _parse_questoes_texto(_texto_prova(), banca="CESPE")
    for q in qs:
        assert len(q["enunciado"]) >= 10, f"Q{q['numero']} enunciado curto"


def test_nao_extrai_gabarito_do_corpo_da_prova():
    """A prova PCI não traz gabarito no corpo — respostas saem vazias
    (evita falsos positivos de 'R. 6 e 7', números de linha, etc.)."""
    qs = _parse_questoes_texto(_texto_prova(), banca="CESPE")
    com_resposta = [q["numero"] for q in qs if q["resposta_correta"]]
    assert com_resposta == [], f"respostas indevidas: {com_resposta}"


def test_aplicacao_gabarito_verdadeiro_por_ordem():
    """Aplicando o gabarito oficial (por número), as 55 questões válidas
    recebem a resposta correta e as 5 anuladas ficam vazias."""
    qs = _parse_questoes_texto(_texto_prova(), banca="CESPE")
    _aplicar_gabarito_externo(qs, dict(_GABARITO_VERDADEIRO))
    byn = {q["numero"]: q for q in qs}

    mismatches = []
    for n, letra in _GABARITO_VERDADEIRO.items():
        esperado = "" if letra == "X" else letra
        if byn[n]["resposta_correta"] != esperado:
            mismatches.append((n, byn[n]["resposta_correta"], esperado))
    assert not mismatches, f"mismatches: {mismatches[:10]}"

    com_resposta = sum(1 for q in qs if q["resposta_correta"])
    assert com_resposta == 60 - len(_ANULADAS) == 55


def test_anuladas_ficam_sem_resposta():
    qs = _parse_questoes_texto(_texto_prova(), banca="CESPE")
    _aplicar_gabarito_externo(qs, dict(_GABARITO_VERDADEIRO))
    byn = {q["numero"]: q for q in qs}
    for n in _ANULADAS:
        assert byn[n]["resposta_correta"] == "", f"Q{n} anulada não deveria ter resposta"


def test_parser_direto_tambem_extrai_60():
    """O parser dedicado, chamado diretamente, também extrai as 60."""
    qs = _parse_cespe_multipla(_texto_prova(), banca="CESPE")
    assert len(qs) == 60
    assert all(q["tipo"] == "multipla_escolha" for q in qs)

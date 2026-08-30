"""Testes da extração de texto base (texto de apoio) na importação de questões.

Cobre:
- _extrair_texto_base (unitário): separa texto de apoio do comando da questão.
- _parse_qconcursos (integração): inclui texto_base no dict da questão.
- INSERT de importação grava a coluna texto_base.

Executar: pytest tests/test_importacao_texto_base.py -v
"""
import os
import sys
import tempfile

# DB temporário antes de importar o app/módulos
_tmp_db = tempfile.NamedTemporaryFile(suffix="_texto_base.db", delete=False)
_tmp_db.close()
os.environ.setdefault("TEST_DB", _tmp_db.name)
os.environ.setdefault("AUTH_ENABLED", "false")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database

database.DB_PATH = _tmp_db.name
database.init_db()

from routers.questoes.importacao import (
    _extrair_texto_base,
    _is_estrategia_format,
    _parse_estrategia,
    _parse_qconcursos,
)


# Amostra representativa do formato Estratégia Concursos (2 questões: múltipla + C/E)
_ESTRATEGIA_SAMPLE = """
Questão 1
2024
Nível Superior em Qualquer Área
FCC
Técnico Judiciário - Área Apoio Especializado (Poder Judiciário da União)
Tribunal Regional do Trabalho de Sergipe (20ª Região)
Questões oficiais
Emprego do pronome relativo
Atenção
: Para responder à questão, baseie-se no texto abaixo.
Do Rubem Braga para Vinicius do Moraes
Gosto muito da crônica que Rubem Braga publicou depois que seu amigo se foi.
Admiro muito essas frases sintéticas, supostamente simples, mas de muitas camadas.
Como nada mais tenho para lhes oferecer, fico recitando essa frase expressiva.
Considere as seguintes orações:
I. Aprecio muito o gênero da crônica.
II. Rubem Braga se destacou no gênero crônica.
As ideias presentes nas orações articulam-se com coerência neste período:
A
É incontestável o talento de Rubem Braga, destacado nas crônicas.
B
No gênero da crônica, ao qual aprecio muito, destacou-se o talento.
C
O talento de Rubem Braga manifestou-se no gênero da crônica.
D
É incontestável o talento de Rubem Braga, no gênero da crônica.
E
Destacou-se no gênero da crônica, pelo talento apreciável.
Essa questão possui comentário do professor no site
4001938438
Questão 2
2024
CESPE (CEBRASPE)
Analista Judiciário (Poder Judiciário da União)
Tribunal Superior Eleitoral
Texto CB1A1-III
Aprendemos desde cedo que a linguagem verbal serve para comunicar.
Comunicar não se limita, entretanto, a transmitir informações.
Considerando os aspectos textuais do texto CB1A1-III, julgue o item seguinte.
As vírgulas foram empregadas para separar expressões de caráter explicativo.
A
Certo.
B
Errado.
Essa questão possui comentário do professor no site
4001938439
"""


class TestParseEstrategia:
    def test_detecta_formato_estrategia(self):
        assert _is_estrategia_format(_ESTRATEGIA_SAMPLE) is True

    def test_extrai_duas_questoes(self):
        qs = _parse_estrategia(_ESTRATEGIA_SAMPLE, materia="Língua Portuguesa")
        assert len(qs) == 2

    def test_multipla_escolha_completa(self):
        qs = _parse_estrategia(_ESTRATEGIA_SAMPLE, materia="Língua Portuguesa")
        q1 = qs[0]
        assert q1["numero"] == 1
        # 5 alternativas preenchidas
        for c in "abcde":
            assert q1[f"alternativa_{c}"], f"alternativa {c} vazia"
        # alternativas distintas (não duplicadas — bug antigo)
        assert q1["alternativa_a"] != q1["alternativa_d"]
        # enunciado real capturado (não o metadado)
        assert "período" in q1["enunciado"].lower()
        # texto de apoio capturado, sem o resíduo 'abaixo.'
        assert q1["texto_base"]
        assert not q1["texto_base"].lower().startswith("abaixo")
        assert "Rubem Braga" in q1["texto_base"]

    def test_certo_errado_detectado(self):
        qs = _parse_estrategia(_ESTRATEGIA_SAMPLE, materia="Língua Portuguesa")
        q2 = qs[1]
        assert q2["numero"] == 2
        assert q2["tipo"] == "certo_errado"
        assert q2["alternativa_a"].lower().startswith("certo")
        assert q2["alternativa_b"].lower().startswith("errado")

    def test_limpeza_ocr_ligadura_fi(self):
        # '&cando' deve virar 'ficando'
        from routers.questoes.importacao import _limpar_ocr_estrategia
        assert _limpar_ocr_estrategia("Esse vou &cando resume") == "Esse vou ficando resume"
        assert "final" in _limpar_ocr_estrategia("resignação &nal de quem")


class TestExtrairTextoBase:
    def test_sem_texto_base_enunciado_curto(self):
        """Enunciado curto não deve gerar texto base."""
        enun = "Assinale a alternativa correta sobre o princípio da legalidade."
        tb, e = _extrair_texto_base(enun)
        assert tb == ""
        assert e == enun

    def test_sem_marcador_nao_separa(self):
        """Enunciado longo sem marcador de texto base não é separado."""
        enun = "A" * 400 + " qual a resposta?"
        tb, e = _extrair_texto_base(enun)
        assert tb == ""
        assert e == enun

    def test_separa_texto_base_com_marcador(self):
        """Enunciado com 'Considere o texto a seguir' + comando é separado."""
        texto_apoio = (
            "Considere o texto a seguir para responder. "
            + "A língua portuguesa é rica em nuances e possibilidades expressivas, "
            "permitindo ao falante construir sentidos diversos conforme o contexto "
            "comunicativo em que se insere a mensagem transmitida ao interlocutor. "
        )
        comando = "Assinale a alternativa que apresenta a análise correta do período."
        tb, e = _extrair_texto_base(texto_apoio + comando)
        assert tb != "", "deveria ter extraído texto base"
        assert "Assinale a alternativa" in e
        assert "língua portuguesa é rica" in tb
        # O comando não deve estar duplicado no texto base
        assert "Assinale a alternativa" not in tb


class TestParseQConcursosTextoBase:
    def test_parse_inclui_campo_texto_base(self):
        """O dict retornado pelo parser QConcursos deve conter a chave texto_base."""
        texto = (
            "Ano: 2023 Banca: FCC Órgão: TRT Prova: Analista\n"
            "Assinale a alternativa correta sobre concordância verbal.\n"
            "A primeira opção\n"
            "B segunda opção\n"
            "C terceira opção\n"
            "D quarta opção\n"
            "E quinta opção\n"
            "Respostas\n1: A\n"
        )
        questoes = _parse_qconcursos(texto, materia_override="Português")
        assert len(questoes) >= 1
        assert "texto_base" in questoes[0]


def teardown_module():
    try:
        os.unlink(_tmp_db.name)
    except OSError:
        pass

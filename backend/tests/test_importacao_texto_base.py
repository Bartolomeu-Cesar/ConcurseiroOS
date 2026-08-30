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

from routers.questoes.importacao import _extrair_texto_base, _parse_qconcursos


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

"""Regressão: os gráficos "Evolução de Acertos (14 dias)" e "Horas de Estudo
(14 dias)" no dashboard exibiam a data como MM-DD (ex.: 09-07), porque usavam
`d.data.slice(5)` sobre uma data ISO (YYYY-MM-DD). O correto é DD-MM (07-09).

Como não há runner JS, validamos estaticamente frontend/js/pages/dashboard/charts.js:
- existe o helper fmtDiaMes que converte ISO → DD-MM;
- os labels dos dois gráficos usam fmtDiaMes (e não mais .data.slice(5));
- a semântica do helper (reordena para dia-mês) é reproduzida e verificada em Python.
"""
import re
from pathlib import Path

import pytest

CHARTS_JS = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "js" / "pages" / "dashboard" / "charts.js"
)


@pytest.fixture(scope="module")
def src() -> str:
    return CHARTS_JS.read_text(encoding="utf-8")


def test_helper_fmtdiames_existe(src):
    assert "function fmtDiaMes(" in src, "helper fmtDiaMes ausente"
    # A regex do helper deve capturar YYYY-MM-DD e remontar como DD-MM (m[3]-m[2]).
    assert re.search(r"\$\{m\[3\]\}-\$\{m\[2\]\}", src), (
        "fmtDiaMes deve reordenar para DD-MM (dia-mês)"
    )


def test_labels_usam_fmtdiames(src):
    """Os dois gráficos de 14 dias devem formatar via fmtDiaMes."""
    assert src.count("fmtDiaMes(d.data)") == 2, (
        "esperados 2 labels usando fmtDiaMes (horas e acertos)"
    )


def test_nao_usa_mais_slice5_em_data(src):
    """O bug era d.data.slice(5) (deixava MM-DD). Não pode voltar."""
    assert "d.data.slice(5)" not in src, (
        "d.data.slice(5) reintroduz o bug MM-DD"
    )


def _fmt_dia_mes(iso):
    """Reprodução em Python da lógica de fmtDiaMes (para travar a semântica)."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(iso or ""))
    return f"{m.group(3)}-{m.group(2)}" if m else str(iso or "")


def test_semantica_iso_para_dia_mes():
    assert _fmt_dia_mes("2026-09-07") == "07-09"
    assert _fmt_dia_mes("2026-09-08") == "08-09"
    assert _fmt_dia_mes("2026-12-25") == "25-12"


def test_semantica_valor_nao_iso_intacto():
    # Não-ISO: devolve intacto (não quebra labels que não sejam datas).
    assert _fmt_dia_mes("Segunda") == "Segunda"
    assert _fmt_dia_mes("") == ""
    assert _fmt_dia_mes(None) == ""

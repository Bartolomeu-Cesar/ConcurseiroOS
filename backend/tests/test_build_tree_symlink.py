"""Regressão: build_tree não deve estourar quando um PDF resolve para fora do PDF_ROOT.

Cenário do bug (relatado em produção): um symlink/atalho dentro de PDF_ROOT aponta
para um PDF em outra pasta (ex.: C:\\Users\\...\\Livros\\x.pdf). entry.resolve()
seguia o link e caía fora da base, e relative_to() lançava ValueError não tratado,
derrubando GET /api/pdf/orfaos com 500.

Correção: build_tree faz fallback para o caminho LÓGICO (sem resolver o link) e, em
último caso, pula a entrada com warning — nunca propaga ValueError.

Executar: pytest tests/test_build_tree_symlink.py -v
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import build_tree


def _coletar_pdfs(nodes):
    """Achata a árvore e retorna a lista de paths de PDF."""
    paths = []
    for n in nodes:
        if n.get("type") == "pdf":
            paths.append(n["path"])
        elif n.get("type") == "folder":
            paths.extend(_coletar_pdfs(n.get("children", [])))
    return paths


def _suporta_symlink(base: Path) -> bool:
    alvo = base / "_probe_target.txt"
    link = base / "_probe_link.txt"
    try:
        alvo.write_text("x")
        link.symlink_to(alvo)
        link.unlink()
        alvo.unlink()
        return True
    except (OSError, NotImplementedError):
        return False


def test_build_tree_pdf_normal_ok():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "aula1.pdf").write_bytes(b"%PDF-1.4\n")
        (root / "Direito").mkdir()
        (root / "Direito" / "aula2.pdf").write_bytes(b"%PDF-1.4\n")
        pdfs = _coletar_pdfs(build_tree(str(root)))
        assert "aula1.pdf" in pdfs
        assert "Direito/aula2.pdf" in pdfs


def test_build_tree_nao_estoura_com_symlink_fora_da_base():
    """O bug: symlink dentro de PDF_ROOT apontando p/ PDF FORA dele."""
    with tempfile.TemporaryDirectory() as base_root, tempfile.TemporaryDirectory() as fora:
        root = Path(base_root)
        (root / "aula1.pdf").write_bytes(b"%PDF-1.4\n")

        # PDF real fora do PDF_ROOT
        externo = Path(fora) / "livro_externo.pdf"
        externo.write_bytes(b"%PDF-1.4\n")

        if not _suporta_symlink(root):
            pytest.skip("Ambiente não suporta symlink (ex.: Windows sem privilégio)")

        # Symlink dentro do PDF_ROOT apontando para o PDF externo
        (root / "atalho_externo.pdf").symlink_to(externo)

        # Não deve lançar ValueError (o bug original)
        arvore = build_tree(str(root))
        pdfs = _coletar_pdfs(arvore)

        # O PDF local continua presente
        assert "aula1.pdf" in pdfs
        # O PDF via symlink foi preservado pelo caminho lógico (não sumiu nem quebrou)
        assert "atalho_externo.pdf" in pdfs


def test_build_tree_symlink_em_subpasta_nao_estoura():
    """Symlink fora da base dentro de uma subpasta também não deve quebrar."""
    with tempfile.TemporaryDirectory() as base_root, tempfile.TemporaryDirectory() as fora:
        root = Path(base_root)
        sub = root / "Livros"
        sub.mkdir()
        externo = Path(fora) / "externo.pdf"
        externo.write_bytes(b"%PDF-1.4\n")

        if not _suporta_symlink(root):
            pytest.skip("Ambiente não suporta symlink")

        (sub / "link.pdf").symlink_to(externo)

        arvore = build_tree(str(root))  # não deve estourar
        pdfs = _coletar_pdfs(arvore)
        assert "Livros/link.pdf" in pdfs

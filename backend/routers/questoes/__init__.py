"""
Questões router package — modularizado em:
- core.py: CRUD (listar, obter, criar, editar, deletar, responder, vincular lote)
- stats.py: Estatísticas, listagens de bancas/matérias/provas/datas
- caderno_erros.py: Caderno de erros com FSRS + revisão interativa
- estudo.py: Daily challenge, active recall, intercalação, questões vinculadas
- importacao.py: Importação via CSV, PDF (OCR) e URL + parsers

IMPORTANTE: A ordem de include_router importa!
Rotas específicas (/api/questoes/stats/*, /api/questoes/erros/*, /api/questoes/bancas, etc)
devem vir ANTES de /api/questoes/{id} para evitar conflito de path params.
"""
from fastapi import APIRouter

from .caderno_erros import router as caderno_erros_router
from .core import router as core_router
from .estudo import router as estudo_router
from .filtros import router as filtros_router
from .importacao import router as importacao_router
from .stats import router as stats_router

router = APIRouter(prefix="", tags=["Questões"])

# Rotas específicas PRIMEIRO (evita que /api/questoes/{id} capture /bancas, /stats, etc)
router.include_router(stats_router)
router.include_router(caderno_erros_router)
router.include_router(filtros_router)
router.include_router(importacao_router)
router.include_router(estudo_router)
# CRUD com /{id} por último
router.include_router(core_router)

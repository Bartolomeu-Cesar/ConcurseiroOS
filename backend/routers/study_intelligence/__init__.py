"""
Study Intelligence router package — modularizado em:
- core.py: Análise geral de inteligência de estudo + next-review + helpers
- techniques.py: Técnicas de estudo (pre-test, calibration, dual-coding, etc)
- retention.py: Curva de esquecimento, alertas, resumo de retenção
- metas.py: Meta adaptativa + detecção de platô
"""
from fastapi import APIRouter

from .core import router as core_router
from .techniques import router as techniques_router
from .retention import router as retention_router
from .metas import router as metas_router

router = APIRouter(prefix="", tags=["Study Intelligence"])

router.include_router(core_router)
router.include_router(techniques_router)
router.include_router(retention_router)
router.include_router(metas_router)

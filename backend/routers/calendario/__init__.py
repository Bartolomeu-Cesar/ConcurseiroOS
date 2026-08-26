"""
Calendário router package — modularizado em:
- core.py: Preferências + agenda do dia (/api/calendario/hoje)
- personalizado.py: CRUD calendário personalizado + atividades + streak
- inteligencia.py: Matérias negligenciadas, micro-revisão, dissertativa, spacing, recomendações
"""
from fastapi import APIRouter

from .core import router as core_router
from .personalizado import router as personalizado_router
from .inteligencia import router as inteligencia_router

router = APIRouter(prefix="", tags=["Calendário"])

router.include_router(core_router)
router.include_router(personalizado_router)
router.include_router(inteligencia_router)

"""
Edital router package — modularizado em:
- core.py: CRUD de tópicos, importação PDF, vinculação PDF, arquivamento
- revisao.py: Notas, revisão SM2/FSRS, revisões pendentes
- mastery.py: Resumos, exportar/importar edital, mastery overview + recalculate
"""
from fastapi import APIRouter

from .core import router as core_router
from .revisao import router as revisao_router
from .mastery import router as mastery_router

# Re-export para compatibilidade: questoes/core.py importa "from routers.edital import _update_single_mastery"
from .mastery import _update_single_mastery  # noqa: F401

router = APIRouter(prefix="", tags=["Edital"])

router.include_router(core_router)
router.include_router(revisao_router)
router.include_router(mastery_router)

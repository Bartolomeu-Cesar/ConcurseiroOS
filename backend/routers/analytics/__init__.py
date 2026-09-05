"""
Analytics router package — modularizado em:
- core.py: Relatórios principais (semanal, diário, radar, heatmap, projeção, previsão, planejador)
- export.py: Exportação, importação, compartilhamento, widgets
- advanced.py: Analytics avançados (curva esquecimento, raio-x, evolução, ROI, weekly wrap)
"""
from fastapi import APIRouter

from .advanced import router as advanced_router
from .core import router as core_router
from .export import router as export_router

router = APIRouter(prefix="", tags=["Analytics"])

router.include_router(core_router)
router.include_router(export_router)
router.include_router(advanced_router)

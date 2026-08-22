"""
Router de Batalha de Questões (Multiplayer) — estilo Duolingo.
Até 5 jogadores, rodadas configuráveis, matérias selecionáveis.
"""
from fastapi import APIRouter

from .crud import router as crud_router
from .gameplay import router as gameplay_router
from .pool import router as pool_router
from .results import router as results_router

router = APIRouter()
router.include_router(crud_router)
router.include_router(gameplay_router)
router.include_router(results_router)
router.include_router(pool_router)

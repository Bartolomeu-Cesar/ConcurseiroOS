"""
Study Room — Módulo de Sala de Estudos Virtual.

Combina sub-routers: core, pomodoro, gamification, metacognition, discussion.
Exporta um único `router` para inclusão no app principal.
"""
from fastapi import APIRouter

from .core import router as core_router
from .discussion import router as discussion_router
from .gamification import router as gamification_router
from .metacognition import router as metacognition_router
from .pomodoro import router as pomodoro_router

# Router combinado — mantém a mesma interface que o monolítico anterior
router = APIRouter()
router.include_router(core_router)
router.include_router(pomodoro_router)
router.include_router(gamification_router)
router.include_router(metacognition_router)
router.include_router(discussion_router)

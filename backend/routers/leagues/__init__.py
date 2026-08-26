"""
Leagues router package — modularizado em:
- helpers.py: Constantes, tiers, XP calculation, bots, rankings
- endpoints.py: Endpoints da liga semanal
"""
from fastapi import APIRouter

from .endpoints import router as endpoints_router

router = APIRouter(prefix="", tags=["Ligas"])

router.include_router(endpoints_router)

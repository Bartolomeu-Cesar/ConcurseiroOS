"""Técnicas de estudo — modularizado por afinidade científica.

Cada submódulo tem seu próprio `router` (mesmo prefixo /api/study-intelligence/*).
Este __init__ agrega todos em um único `router`, mantendo backward-compat total:
`from .techniques import router` continua funcionando no pacote pai.

Submódulos:
- metacognition: pre-test, self-explanation, calibration, overconfidence
- encoding: contextual-variation, successive-relearning, dual-coding, concrete-examples, memory-palace, elaboration
- wellbeing: burnout, blocked-practice, sleep-consolidation, adaptive-break, anxiety-exposure
- mastery: overlearning, transfer-test, milestones, error-patterns, minimum-dose
- retrieval: retrieval-warmup, brain-dump
- intentions: implementation intentions, temporal-landmark, spacing-gap, expressive-writing
- banca: banca-profile, banca-training
- social_challenge: peer-teaching, boss-battle, testing-boundaries
"""

from fastapi import APIRouter

from .banca import router as banca_router
from .closedbook import router as closedbook_router
from .encoding import router as encoding_router
from .intentions import router as intentions_router
from .interpolated import router as interpolated_router
from .jol import router as jol_router
from .mastery import router as mastery_router
from .metacognition import router as metacognition_router
from .retrieval import router as retrieval_router
from .social_challenge import router as social_challenge_router
from .wellbeing import router as wellbeing_router

router = APIRouter(prefix="", tags=["Study Intelligence"])

router.include_router(metacognition_router)
router.include_router(encoding_router)
router.include_router(wellbeing_router)
router.include_router(mastery_router)
router.include_router(retrieval_router)
router.include_router(intentions_router)
router.include_router(banca_router)
router.include_router(social_challenge_router)
router.include_router(jol_router)
router.include_router(closedbook_router)
router.include_router(interpolated_router)

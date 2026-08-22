"""Router do Treinador Inteligente e Calendário Semanal.

Intelligence features:
1. Análise de padrão de erros (tópico-específico)
2. Ritmo adaptativo (horas/dia necessárias vs ritmo atual)
3. Curva de esquecimento personalizada (FSRS stability)
4. Distribuição por peso da banca (Raio-X frequency)
5. Detecção de platô (evolução estagnada)
6. Micro-metas dinâmicas (tópico mais fraco dentro da matéria)
7. Horário ótimo (baseado em padrões de estudo)
8. Sprint mode (< 30 dias = modo revisão intensiva)
"""
from fastapi import APIRouter

from .calendario import router as calendario_router
from .main import router as main_router
from .sugestoes import router as sugestoes_router
from .trilha import router as trilha_router

router = APIRouter(prefix="", tags=["Treinador Inteligente"])
router.include_router(main_router)
router.include_router(trilha_router)
router.include_router(calendario_router)
router.include_router(sugestoes_router)

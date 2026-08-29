"""
Social router package — modularizado em:
- helpers.py: Pydantic models + funções auxiliares compartilhadas
- friends.py: Amizades (listar, adicionar, aceitar, rejeitar, remover)
- chat.py: Chat direto entre amigos
- groups.py: Grupos de estudo (CRUD, membros, ranking, desafios)
- feed.py: Activity feed + perfis sociais
- status.py: Status de presença (o que cada usuário está fazendo agora)
"""
from fastapi import APIRouter

from .friends import router as friends_router
from .chat import router as chat_router
from .groups import router as groups_router
from .feed import router as feed_router
from .status import router as status_router

router = APIRouter(prefix="", tags=["Social"])

router.include_router(friends_router)
router.include_router(chat_router)
router.include_router(groups_router)
router.include_router(feed_router)
router.include_router(status_router)

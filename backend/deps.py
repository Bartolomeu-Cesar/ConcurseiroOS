"""Dependências compartilhadas entre routers."""
import jwt
from fastapi import Header, HTTPException

from settings import settings

DEFAULT_USER_ID = 1


async def get_user_id(authorization: str = Header(None)) -> int:
    """Extrai user_id do token JWT.

    Comportamento:
    - AUTH_ENABLED=false → sempre retorna DEFAULT_USER_ID (modo single-user)
    - AUTH_ENABLED=true + token válido → retorna user_id do token
    - AUTH_ENABLED=true + sem token/inválido → retorna DEFAULT_USER_ID (guest mode)

    Nota: Em modo AUTH_ENABLED=true, sem token = user_id=1 para manter compatibilidade
    com o fluxo de guest. A proteção real é no frontend que redireciona para login.
    """
    if not settings.AUTH_ENABLED:
        return DEFAULT_USER_ID

    # Se não tem token, retorna default (guest mode)
    if not authorization or not authorization.startswith("Bearer "):
        return DEFAULT_USER_ID

    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        # Token inválido = guest
        return DEFAULT_USER_ID


async def get_authenticated_user_id(authorization: str = Header(None)) -> int:
    """Versão estrita: EXIGE autenticação quando AUTH_ENABLED=true.

    Usar em endpoints sensíveis (backup, upgrade, etc.)
    """
    if not settings.AUTH_ENABLED:
        return DEFAULT_USER_ID

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")

    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return int(payload["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token inválido")

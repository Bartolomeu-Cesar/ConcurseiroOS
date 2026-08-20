"""Dependências compartilhadas entre routers."""
import jwt
from fastapi import Header, HTTPException

from settings import settings

DEFAULT_USER_ID = 1


async def get_user_id(authorization: str = Header(None)) -> int:
    """Extrai user_id do token JWT.

    - Se AUTH_ENABLED=false → retorna DEFAULT_USER_ID (modo single-user)
    - Se AUTH_ENABLED=true e token válido → retorna user_id do token
    - Se AUTH_ENABLED=true e sem token → HTTPException 401
    """
    if not settings.AUTH_ENABLED:
        return DEFAULT_USER_ID

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token não fornecido")

    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        return int(payload["sub"])
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token inválido ou expirado")

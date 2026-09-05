"""Dependências compartilhadas entre routers."""
import jwt
from fastapi import Header, HTTPException, Query

from logger import set_user_id_context
from settings import settings

DEFAULT_USER_ID = 1


def _decode_user_id(token: str) -> int:
    """Valida um access token JWT e retorna o user_id. Levanta 401 se inválido."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        # Rejeitar refresh tokens — só aceita access ou tokens legados (sem type)
        if payload.get("type") == "refresh":
            raise HTTPException(status_code=401, detail="Refresh token não é aceito para autenticação")
        user_id = int(payload["sub"])
        set_user_id_context(user_id)
        return user_id
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado") from None
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise HTTPException(status_code=401, detail="Token inválido") from None


async def get_user_id(
    authorization: str = Header(None),
    token: str = Query(None),
) -> int:
    """Extrai user_id do token JWT.

    Comportamento:
    - AUTH_ENABLED=false → sempre retorna DEFAULT_USER_ID (modo single-user)
    - AUTH_ENABLED=true + token válido → retorna user_id do token
    - AUTH_ENABLED=true + sem token/inválido → retorna 401 (exige autenticação)

    O token é lido do header `Authorization: Bearer <t>` OU, como alternativa,
    da query string `?token=<t>`. A query é necessária para o endpoint que serve
    o binário do PDF: o PDF.js embutido carrega a URL diretamente no iframe e o
    navegador NÃO anexa o header Authorization nesse fetch. Ler o token da query
    permite servir o PDF autenticado com range requests nativos do PDF.js.
    """
    if not settings.AUTH_ENABLED:
        set_user_id_context(DEFAULT_USER_ID)
        return DEFAULT_USER_ID

    raw = None
    if authorization and authorization.startswith("Bearer "):
        raw = authorization.replace("Bearer ", "")
    elif token:
        raw = token

    if not raw:
        raise HTTPException(status_code=401, detail="Token não fornecido")

    return _decode_user_id(raw)


async def get_optional_user_id(authorization: str = Header(None)) -> int:
    """Versão permissiva: retorna DEFAULT_USER_ID se sem token (para endpoints públicos).

    Usar apenas em endpoints que devem funcionar sem login (ex: health, docs).
    """
    if not settings.AUTH_ENABLED:
        set_user_id_context(DEFAULT_USER_ID)
        return DEFAULT_USER_ID

    if not authorization or not authorization.startswith("Bearer "):
        set_user_id_context(DEFAULT_USER_ID)
        return DEFAULT_USER_ID

    token = authorization.replace("Bearer ", "")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        # Rejeitar refresh tokens
        if payload.get("type") == "refresh":
            set_user_id_context(DEFAULT_USER_ID)
            return DEFAULT_USER_ID
        user_id = int(payload["sub"])
        set_user_id_context(user_id)
        return user_id
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, ValueError):
        set_user_id_context(DEFAULT_USER_ID)
        return DEFAULT_USER_ID


# Alias para compatibilidade — endpoints sensíveis usam o mesmo que get_user_id agora
get_authenticated_user_id = get_user_id

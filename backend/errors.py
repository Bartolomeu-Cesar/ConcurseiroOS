"""Códigos de erro padronizados para HTTPException.

Uso:
    from errors import raise_not_found, raise_forbidden, raise_conflict, raise_bad_request

Formato da resposta:
    {"detail": "Mensagem legível", "code": "RESOURCE_NOT_FOUND"}
"""
from fastapi import HTTPException


# ============================================================
# ERROR CODES
# ============================================================

# 400 - Bad Request
INVALID_INPUT = "INVALID_INPUT"
MISSING_FIELD = "MISSING_FIELD"
VALIDATION_ERROR = "VALIDATION_ERROR"

# 401 - Unauthorized
UNAUTHORIZED = "UNAUTHORIZED"
TOKEN_EXPIRED = "TOKEN_EXPIRED"
TOKEN_INVALID = "TOKEN_INVALID"

# 403 - Forbidden
FORBIDDEN = "FORBIDDEN"
NOT_OWNER = "NOT_OWNER"
PLAN_LIMIT = "PLAN_LIMIT"

# 404 - Not Found
NOT_FOUND = "NOT_FOUND"
USER_NOT_FOUND = "USER_NOT_FOUND"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"

# 409 - Conflict
ALREADY_EXISTS = "ALREADY_EXISTS"
DUPLICATE_ENTRY = "DUPLICATE_ENTRY"

# 429 - Too Many Requests
RATE_LIMITED = "RATE_LIMITED"


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def raise_not_found(detail: str = "Recurso não encontrado", code: str = NOT_FOUND):
    """Levanta 404 com code padronizado."""
    raise HTTPException(status_code=404, detail={"message": detail, "code": code})


def raise_bad_request(detail: str = "Dados inválidos", code: str = INVALID_INPUT):
    """Levanta 400 com code padronizado."""
    raise HTTPException(status_code=400, detail={"message": detail, "code": code})


def raise_forbidden(detail: str = "Acesso negado", code: str = FORBIDDEN):
    """Levanta 403 com code padronizado."""
    raise HTTPException(status_code=403, detail={"message": detail, "code": code})


def raise_conflict(detail: str = "Recurso já existe", code: str = ALREADY_EXISTS):
    """Levanta 409 com code padronizado."""
    raise HTTPException(status_code=409, detail={"message": detail, "code": code})


def raise_unauthorized(detail: str = "Não autenticado", code: str = UNAUTHORIZED):
    """Levanta 401 com code padronizado."""
    raise HTTPException(status_code=401, detail={"message": detail, "code": code})

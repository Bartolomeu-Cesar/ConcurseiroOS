"""Request lifecycle middleware for ConcurseiroOS.

Provides:
- RequestIdMiddleware: generates unique request_id per request, sets contextvar
- AccessLogMiddleware: logs request start/end with duration_ms
- Exception handlers: standardized JSON error responses with request_id correlation
"""

import time
import traceback
import uuid
from datetime import datetime, timezone

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

from logger import get_request_id, log, set_request_id, set_user_id_context  # noqa: F401 — re-export get_request_id

# ============================================================
# REQUEST ID MIDDLEWARE
# ============================================================


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns a unique request_id (8-char UUID4) to each request and stores it in contextvars.

    Also sets the X-Request-ID response header for traceability.
    """

    async def dispatch(self, request: StarletteRequest, call_next) -> Response:
        # Use incoming header if present, otherwise generate 8-char short id
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]

        # Store in contextvars for logger
        set_request_id(request_id)

        # Store on request state for other middleware/handlers
        request.state.request_id = request_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ============================================================
# ACCESS LOG MIDDLEWARE
# ============================================================


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Logs request start and end with method, path, status_code, and duration_ms.

    Skips logging for static assets and health checks to reduce noise.
    """

    # Paths/extensions to skip
    _skip_extensions = (
        ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".gif",
        ".ico", ".woff", ".woff2", ".ttf", ".mjs", ".map", ".json",
        ".html", ".pdf",
    )
    _skip_paths = ("/pdfjs/", "/css/", "/js/", "/icons/", "/images/", "/fonts/")

    def _should_skip(self, path: str) -> bool:
        """Skip logging for static assets and health endpoints."""
        if path in ("/api/health", "/api/status"):
            return True
        if path.endswith(self._skip_extensions):
            return True
        if any(path.startswith(sp) for sp in self._skip_paths):
            return True
        return bool(not path.startswith("/api/"))

    async def dispatch(self, request: StarletteRequest, call_next) -> Response:
        path = request.url.path
        method = request.method

        if self._should_skip(path):
            return await call_next(request)

        start_time = time.perf_counter()

        log.info(
            "Request started",
            method=method,
            path=path,
        )

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
            log.error(
                "Request failed",
                method=method,
                path=path,
                duration_ms=duration_ms,
                error=str(exc),
            )
            raise

        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        status_code = response.status_code

        level = "info" if status_code < 400 else "warning" if status_code < 500 else "error"
        getattr(log, level)(
            "Request completed",
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
        )

        return response


# ============================================================
# EXCEPTION HANDLERS (to be registered on the FastAPI app)
# ============================================================


def _build_error_response(
    status: int,
    detail,
    request_id: str,
) -> JSONResponse:
    """Build a standardized error JSON response."""
    return JSONResponse(
        status_code=status,
        content={
            "error": True,
            "status": status,
            "detail": detail,
            "request_id": request_id,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        headers={"X-Request-ID": request_id},
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle FastAPI/Starlette HTTPException — preserves status_code and detail."""
    request_id = getattr(request.state, "request_id", None) or get_request_id() or "unknown"
    log.warning(
        f"HTTPException {exc.status_code}: {exc.detail}",
        method=request.method,
        path=request.url.path,
        status_code=exc.status_code,
    )
    return _build_error_response(
        status=exc.status_code,
        detail=exc.detail,
        request_id=request_id,
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle Pydantic RequestValidationError — returns 422 with field details."""
    request_id = getattr(request.state, "request_id", None) or get_request_id() or "unknown"
    errors = exc.errors()
    # Simplify error output for the client
    details = [
        {
            "loc": list(err.get("loc", [])),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in errors
    ]
    log.warning(
        "Validation error",
        method=request.method,
        path=request.url.path,
        errors=details,
    )
    return _build_error_response(
        status=422,
        detail=details,
        request_id=request_id,
    )


async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for unhandled exceptions — logs full traceback with request_id."""
    request_id = getattr(request.state, "request_id", None) or get_request_id() or "unknown"
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    log.error(
        f"Unhandled {type(exc).__name__}: {exc}",
        method=request.method,
        path=request.url.path,
        traceback=tb,
    )
    return _build_error_response(
        status=500,
        detail="Erro interno do servidor",
        request_id=request_id,
    )

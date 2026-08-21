import mimetypes
import time

# Força o MIME type correto para arquivos .mjs e .js (necessário para PDF.js)
mimetypes.add_type("application/javascript", ".mjs", strict=True)
mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("text/javascript", ".mjs", strict=True)
mimetypes.add_type("text/javascript", ".js", strict=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from routers import (
    analytics, auth, bookmarks, cadernos, calendario, ciclo, dashboard,
    desafios, edital, feynman, flashcards, misc, notas, notifications, pdf,
    planejador, questoes, simulados, streaks, sumulas, treinador,
    leagues, ai_tutor, social, batalha, admin
)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from database import init_db
from logger import log
from settings import settings

# ============================================================
# CONFIGURAÇÃO
# ============================================================

APP_START_TIME = time.time()

# ============================================================
# RATE LIMITING MIDDLEWARE
# ============================================================


class RateLimitMiddleware(BaseHTTPMiddleware):
    """IP-based rate limiting with in-memory storage and TTL cleanup."""

    def __init__(self, app):
        super().__init__(app)
        # {ip: [(timestamp, ...), ...]}
        self._requests: dict = {}
        self._last_cleanup = time.time()
        self._cleanup_interval = 60  # cleanup every 60s

    def _cleanup(self, now: float):
        """Remove entries older than 60s."""
        cutoff = now - 60
        ips_to_delete = []
        for ip, timestamps in self._requests.items():
            # Filter out old timestamps
            self._requests[ip] = [ts for ts in timestamps if ts > cutoff]
            if not self._requests[ip]:
                ips_to_delete.append(ip)
        for ip in ips_to_delete:
            del self._requests[ip]
        self._last_cleanup = now

    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path

        # Exempt health check endpoint
        if path == "/api/health" or path == "/api/status":
            return await call_next(request)

        now = time.time()

        # Periodic cleanup
        if now - self._last_cleanup > self._cleanup_interval:
            self._cleanup(now)

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"

        # Skip rate limiting for test clients (testclient uses "testclient" as host)
        if client_ip == "testclient":
            return await call_next(request)

        # Determine limit based on path
        if path.startswith("/api/auth"):
            limit = settings.RATE_LIMIT_AUTH
        else:
            limit = settings.RATE_LIMIT_GENERAL

        # Get request history for this IP+path_type
        key = f"{client_ip}:auth" if path.startswith("/api/auth") else client_ip

        if key not in self._requests:
            self._requests[key] = []

        # Filter to last 60 seconds
        cutoff = now - 60
        self._requests[key] = [ts for ts in self._requests[key] if ts > cutoff]

        # Check limit
        if len(self._requests[key]) >= limit:
            return Response(
                content='{"detail":"Too Many Requests. Tente novamente em alguns instantes."}',
                status_code=429,
                media_type="application/json",
            )

        # Record this request
        self._requests[key].append(now)

        return await call_next(request)


# ============================================================
# SECURITY HEADERS MIDDLEWARE
# ============================================================


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: blob: https:; "
            "font-src 'self' https://cdn.jsdelivr.net; "
            "connect-src 'self' http://localhost:* ws://localhost:*; "
            "worker-src 'self' blob:; "
            "frame-src 'self' blob:"
        )
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        return response


# ============================================================
# APP SETUP — Conditional docs based on ENV
# ============================================================

_is_production = settings.ENV == "production"

app = FastAPI(
    title="ConcurseiroOS API",
    description="API do sistema de estudos para concursos públicos",
    version=settings.APP_VERSION,
    docs_url=None if _is_production else "/docs",
    redoc_url=None if _is_production else "/redoc",
    openapi_url=None if _is_production else "/openapi.json",
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# GLOBAL EXCEPTION HANDLER
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error(f"Unhandled error on {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Erro interno do servidor"}
    )


# ============================================================
# INICIALIZAÇÃO DO BANCO
# ============================================================

log.info("ConcurseiroOS starting...")
init_db()

# Auto-backup diário
from backup import auto_backup_if_needed

auto_backup_if_needed(settings.DB_PATH)

# Disponibilizar APP_START_TIME para o router misc
misc.APP_START_TIME = APP_START_TIME
misc.DB_PATH = settings.DB_PATH

# ============================================================
# CONFIGURAR PDF_ROOT NOS ROUTERS
# ============================================================

pdf.set_pdf_root(settings.PDF_ROOT)

# ============================================================
# INCLUIR ROUTERS
# ============================================================

app.include_router(pdf.router)
app.include_router(auth.router)
app.include_router(edital.router)
app.include_router(flashcards.router)
app.include_router(questoes.router)
app.include_router(simulados.router)
app.include_router(ciclo.router)
app.include_router(streaks.router)
app.include_router(sumulas.router)
app.include_router(dashboard.router)
app.include_router(analytics.router)
app.include_router(treinador.router)
app.include_router(calendario.router)
app.include_router(planejador.router)
app.include_router(bookmarks.router)
app.include_router(notas.router)
app.include_router(cadernos.router)
app.include_router(feynman.router)
app.include_router(desafios.router)
app.include_router(notifications.router)
app.include_router(leagues.router)
app.include_router(ai_tutor.router)
app.include_router(social.router)
app.include_router(batalha.router)
app.include_router(admin.router)
app.include_router(misc.router)


# ============================================================
# CORREÇÃO DO MIME TYPE PARA .mjs / .js (PDF.js)
# ============================================================

class FixedStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if path.endswith((".mjs", ".js")):
            response.headers["content-type"] = "application/javascript; charset=utf-8"
        return response


# Monta o frontend com a correção (DEVE SER O ÚLTIMO)
app.mount("/", FixedStaticFiles(directory="../frontend", html=True), name="frontend")

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
from routers import ciclo, dashboard, edital, flashcards, misc, pdf, questoes, simulados, streaks, treinador
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

# Registrar tempo de início para o health check
APP_START_TIME = time.time()

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
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: blob:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "worker-src 'self' blob:; "
            "frame-src 'self' blob:"
        )
        return response


# ============================================================
# APP SETUP
# ============================================================

app = FastAPI(
    title="ConcurseiroOS API",
    description="API do sistema de estudos para concursos públicos",
    version=settings.APP_VERSION,
    docs_url="/docs",
    redoc_url="/redoc"
)
app.add_middleware(SecurityHeadersMiddleware)
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
app.include_router(edital.router)
app.include_router(flashcards.router)
app.include_router(questoes.router)
app.include_router(simulados.router)
app.include_router(ciclo.router)
app.include_router(streaks.router)
app.include_router(dashboard.router)
app.include_router(treinador.router)
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

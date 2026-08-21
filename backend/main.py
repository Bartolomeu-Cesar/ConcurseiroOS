import mimetypes
import time

# Força o MIME type correto para arquivos .mjs e .js (necessário para PDF.js)
mimetypes.add_type("application/javascript", ".mjs", strict=True)
mimetypes.add_type("application/javascript", ".js", strict=True)
mimetypes.add_type("text/javascript", ".mjs", strict=True)
mimetypes.add_type("text/javascript", ".js", strict=True)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
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
# OPENAPI TAGS METADATA
# ============================================================

tags_metadata = [
    {
        "name": "Autenticação",
        "description": "Registro, login via código email, verificação, perfil e gerenciamento de planos.",
    },
    {
        "name": "Dashboard",
        "description": "Visão consolidada de métricas: horas de estudo, progresso no edital, questões e flashcards.",
    },
    {
        "name": "Questões",
        "description": "CRUD de questões, responder, importar CSV/PDF, estatísticas e caderno de erros.",
    },
    {
        "name": "Batalha de Questões",
        "description": "Modo multiplayer estilo Duolingo: crie salas, convide até 5 jogadores e dispute rodadas de questões.",
    },
    {
        "name": "Treinador Inteligente",
        "description": "Motor de recomendação com 8 camadas de inteligência: padrão de erros, ritmo adaptativo, FSRS, distribuição por banca, detecção de platô, micro-metas, horário ótimo e sprint mode.",
    },
    {
        "name": "Edital",
        "description": "Gerenciamento de tópicos do edital, progresso por matéria e cargo.",
    },
    {
        "name": "Flashcards",
        "description": "Sistema de repetição espaçada (SM-2/FSRS) para flashcards.",
    },
    {
        "name": "Simulados",
        "description": "Criação e execução de simulados cronometrados com questões do banco.",
    },
    {
        "name": "Ciclo de Estudos",
        "description": "Planejamento de ciclo de matérias com horas-alvo e controle de progresso.",
    },
    {
        "name": "Streaks",
        "description": "Rastreamento de sequências de estudo diárias e metas cumpridas.",
    },
    {
        "name": "Súmulas",
        "description": "Banco de súmulas jurídicas para estudo e revisão.",
    },
    {
        "name": "Analytics",
        "description": "Análises avançadas de desempenho, evolução e padrões de estudo.",
    },
    {
        "name": "Calendário",
        "description": "Calendário personalizado de estudos com distribuição por dia da semana.",
    },
    {
        "name": "Planejador",
        "description": "Planejador semanal de matérias e horas de estudo.",
    },
    {
        "name": "Bookmarks",
        "description": "Marcadores de página em PDFs com labels e cores.",
    },
    {
        "name": "Notas",
        "description": "Anotações vinculadas a PDFs e tópicos do edital.",
    },
    {
        "name": "Cadernos",
        "description": "Organização de questões e tópicos em cadernos temáticos.",
    },
    {
        "name": "Feynman",
        "description": "Técnica Feynman: explicações próprias para fixar conteúdo.",
    },
    {
        "name": "Desafios",
        "description": "Desafios de estudo com metas temporais (questões, horas, tópicos).",
    },
    {
        "name": "Notificações",
        "description": "Sistema de notificações e lembretes de estudo.",
    },
    {
        "name": "Ligas",
        "description": "Sistema de ligas e competição entre estudantes.",
    },
    {
        "name": "AI Tutor",
        "description": "Tutor de IA para explicações, dúvidas e geração de conteúdo.",
    },
    {
        "name": "Social",
        "description": "Funcionalidades sociais: amigos, ranking e compartilhamento.",
    },
    {
        "name": "Admin",
        "description": "Painel administrativo: gestão de usuários, planos e sistema.",
    },
    {
        "name": "PDF",
        "description": "Gerenciamento e leitura de PDFs com progresso de leitura.",
    },
    {
        "name": "Sistema",
        "description": "Health check, status, backup e informações do sistema.",
    },
]

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

        # Exempt static assets from rate limiting (CSS, JS, images, fonts, PDF.js, etc.)
        static_exts = ('.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.woff', '.woff2', '.ttf', '.mjs', '.map', '.json', '.html', '.pdf')
        static_paths = ('/pdfjs/', '/css/', '/js/', '/icons/', '/images/', '/fonts/')
        if path.endswith(static_exts) or any(path.startswith(sp) for sp in static_paths):
            return await call_next(request)

        # Also exempt non-API paths (frontend files served as static)
        if not path.startswith("/api/"):
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

        # Cache-Control headers based on content type
        path = request.url.path
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        elif path.endswith((".css", ".js", ".svg", ".mjs", ".woff2", ".woff", ".ttf")):
            response.headers["Cache-Control"] = "public, max-age=604800"
        elif path.endswith(".html") or path == "/":
            response.headers["Cache-Control"] = "no-cache"
        return response


# ============================================================
# APP SETUP — Conditional docs based on ENV
# ============================================================

_is_production = settings.ENV == "production"

app = FastAPI(
    title="ConcurseiroOS API",
    description="""
## 📚 ConcurseiroOS — Plataforma de Estudos para Concursos Públicos

Sistema completo de gerenciamento de estudos com:

- **Questões**: Banco de questões com importação CSV/PDF, estatísticas e caderno de erros
- **Treinador Inteligente**: Recomendações personalizadas com 8 camadas de IA
- **Batalha de Questões**: Modo multiplayer competitivo estilo Duolingo
- **Repetição Espaçada**: Flashcards com algoritmo SM-2/FSRS
- **Edital**: Controle de progresso por tópico, matéria e cargo
- **Simulados**: Provas cronometradas com banco de questões
- **Dashboard**: Métricas consolidadas de estudo e evolução
- **Analytics**: Análises avançadas de desempenho

### Autenticação

A API usa JWT Bearer tokens. Obtenha um token via:
1. `POST /api/auth/register` — Registrar novo usuário
2. `POST /api/auth/login` — Solicitar código de verificação
3. `POST /api/auth/verify-code` — Validar código e obter token

Inclua o token no header: `Authorization: Bearer <token>`
""",
    version=settings.APP_VERSION,
    contact={
        "name": "ConcurseiroOS",
        "url": "https://github.com/concurseiroos",
    },
    license_info={
        "name": "MIT",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=tags_metadata,
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
app.add_middleware(GZipMiddleware, minimum_size=500)


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
# API OVERVIEW ENDPOINT
# ============================================================

@app.get("/api", summary="Visão geral da API", tags=["Sistema"],
         description="Retorna uma visão geral dos endpoints disponíveis agrupados por categoria. Útil para consumidores que não usam Swagger.")
def api_overview():
    """Retorna JSON com endpoints agrupados por categoria."""
    return {
        "name": "ConcurseiroOS API",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "endpoints": {
            "autenticacao": {
                "description": "Registro, login e perfil",
                "routes": [
                    {"method": "POST", "path": "/api/auth/register", "summary": "Registrar novo usuário"},
                    {"method": "POST", "path": "/api/auth/login", "summary": "Solicitar código de login"},
                    {"method": "POST", "path": "/api/auth/verify-code", "summary": "Verificar código e obter token"},
                    {"method": "GET", "path": "/api/auth/me", "summary": "Dados do usuário autenticado"},
                    {"method": "PUT", "path": "/api/auth/profile", "summary": "Atualizar perfil"},
                    {"method": "GET", "path": "/api/auth/status", "summary": "Status da autenticação"},
                ],
            },
            "dashboard": {
                "description": "Métricas consolidadas de estudo",
                "routes": [
                    {"method": "GET", "path": "/api/dashboard", "summary": "Dashboard principal com métricas"},
                ],
            },
            "questoes": {
                "description": "Banco de questões com CRUD, respostas e estatísticas",
                "routes": [
                    {"method": "GET", "path": "/api/questoes", "summary": "Listar questões com filtros"},
                    {"method": "POST", "path": "/api/questoes", "summary": "Criar questão"},
                    {"method": "GET", "path": "/api/questoes/{id}", "summary": "Obter questão por ID"},
                    {"method": "PUT", "path": "/api/questoes/{id}", "summary": "Editar questão"},
                    {"method": "POST", "path": "/api/questoes/{id}/responder", "summary": "Responder questão"},
                    {"method": "GET", "path": "/api/questoes/stats/geral", "summary": "Estatísticas gerais"},
                    {"method": "POST", "path": "/api/questoes/importar-csv", "summary": "Importar questões via CSV"},
                ],
            },
            "batalha": {
                "description": "Batalha de questões multiplayer",
                "routes": [
                    {"method": "POST", "path": "/api/batalha/criar", "summary": "Criar sala de batalha"},
                    {"method": "POST", "path": "/api/batalha/entrar", "summary": "Entrar em sala"},
                    {"method": "GET", "path": "/api/batalha/sala/{codigo}", "summary": "Status da sala"},
                    {"method": "POST", "path": "/api/batalha/iniciar/{codigo}", "summary": "Iniciar batalha"},
                    {"method": "POST", "path": "/api/batalha/responder/{codigo}", "summary": "Responder questão"},
                    {"method": "GET", "path": "/api/batalha/ranking/{codigo}", "summary": "Ranking final"},
                ],
            },
            "treinador": {
                "description": "Treinador inteligente com recomendações personalizadas",
                "routes": [
                    {"method": "GET", "path": "/api/treinador", "summary": "Recomendações inteligentes"},
                    {"method": "GET", "path": "/api/trilha-diaria", "summary": "Trilha de estudo do dia"},
                    {"method": "GET", "path": "/api/calendario-semanal", "summary": "Calendário semanal"},
                    {"method": "GET", "path": "/api/treinador/sugestao-rapida", "summary": "Sugestão rápida de matéria"},
                ],
            },
            "edital": {
                "description": "Gerenciamento de tópicos e progresso do edital",
                "routes": [
                    {"method": "GET", "path": "/api/edital", "summary": "Listar tópicos do edital"},
                    {"method": "POST", "path": "/api/edital", "summary": "Adicionar tópico"},
                ],
            },
            "flashcards": {
                "description": "Sistema de repetição espaçada",
                "routes": [
                    {"method": "GET", "path": "/api/flashcards", "summary": "Listar flashcards"},
                    {"method": "POST", "path": "/api/flashcards", "summary": "Criar flashcard"},
                    {"method": "POST", "path": "/api/flashcards/{id}/review", "summary": "Revisar flashcard"},
                ],
            },
            "simulados": {
                "description": "Simulados cronometrados",
                "routes": [
                    {"method": "GET", "path": "/api/simulados", "summary": "Listar simulados"},
                    {"method": "POST", "path": "/api/simulados", "summary": "Criar simulado"},
                ],
            },
            "sistema": {
                "description": "Status e saúde do sistema",
                "routes": [
                    {"method": "GET", "path": "/api/health", "summary": "Health check"},
                    {"method": "GET", "path": "/api/status", "summary": "Status detalhado"},
                    {"method": "GET", "path": "/api", "summary": "Esta visão geral"},
                ],
            },
        },
    }


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

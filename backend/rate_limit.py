"""Rate limiting middleware using SQLite (multi-worker safe).

Uses a separate rate_limit.db with WAL mode for concurrent access.
"""
import sqlite3
import time
from pathlib import Path

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response

from settings import settings

_DB_PATH = Path(__file__).parent / "rate_limit.db"
_WINDOW_SECONDS = 60  # 1 minute sliding window


def _get_connection() -> sqlite3.Connection:
    """Create a new SQLite connection with WAL mode."""
    conn = sqlite3.connect(str(_DB_PATH), timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=3000")
    return conn


def _init_db():
    """Create the rate_limits table if it doesn't exist."""
    conn = _get_connection()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rate_limits (
                ip TEXT NOT NULL,
                endpoint_type TEXT NOT NULL,
                timestamp REAL NOT NULL,
                PRIMARY KEY (ip, endpoint_type, timestamp)
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_rate_limits_cleanup
            ON rate_limits (timestamp)
        """)
        conn.commit()
    finally:
        conn.close()


# Initialize DB on module import
_init_db()


def _cleanup(conn: sqlite3.Connection, now: float):
    """Delete entries older than the window."""
    cutoff = now - _WINDOW_SECONDS
    conn.execute("DELETE FROM rate_limits WHERE timestamp < ?", (cutoff,))
    conn.commit()


def _count_requests(conn: sqlite3.Connection, identifier: str, endpoint_type: str, now: float) -> int:
    """Count requests in the current window for a given identifier+endpoint_type."""
    cutoff = now - _WINDOW_SECONDS
    cursor = conn.execute(
        "SELECT COUNT(*) FROM rate_limits WHERE ip = ? AND endpoint_type = ? AND timestamp > ?",
        (identifier, endpoint_type, cutoff),
    )
    return cursor.fetchone()[0]


def _record_request(conn: sqlite3.Connection, identifier: str, endpoint_type: str, now: float):
    """Record a new request timestamp."""
    try:
        conn.execute(
            "INSERT INTO rate_limits (ip, endpoint_type, timestamp) VALUES (?, ?, ?)",
            (identifier, endpoint_type, now),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        # Extremely unlikely: same ip+endpoint_type+timestamp (microsecond collision)
        # Add a tiny offset and retry
        conn.execute(
            "INSERT OR IGNORE INTO rate_limits (ip, endpoint_type, timestamp) VALUES (?, ?, ?)",
            (identifier, endpoint_type, now + 0.000001),
        )
        conn.commit()


def check_rate_limit(identifier: str, endpoint_type: str, limit: int) -> tuple[bool, int]:
    """Check if the identifier is within rate limits.

    Returns (True, 0) if allowed, (False, retry_after_seconds) if rate limited.
    Records the request if allowed.
    """
    now = time.time()
    conn = _get_connection()
    try:
        # Periodic cleanup (~1% of requests)
        import random
        if random.random() < 0.01:
            _cleanup(conn, now)

        count = _count_requests(conn, identifier, endpoint_type, now)
        if count >= limit:
            # Calculate when the oldest request in window expires
            cutoff = now - _WINDOW_SECONDS
            oldest = conn.execute(
                "SELECT MIN(timestamp) FROM rate_limits WHERE ip = ? AND endpoint_type = ? AND timestamp > ?",
                (identifier, endpoint_type, cutoff),
            ).fetchone()[0]
            retry_after = max(1, int((oldest + _WINDOW_SECONDS) - now)) if oldest else _WINDOW_SECONDS
            return False, retry_after

        _record_request(conn, identifier, endpoint_type, now)
        return True, 0
    finally:
        conn.close()


# Endpoints de auth SENSÍVEIS (anti brute-force). Os demais /api/auth/* são
# leituras de app e usam o limite geral.
_AUTH_SENSITIVE = (
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/verify-code",
    "/api/auth/refresh",
)


def classify_endpoint(path: str) -> tuple[str, int]:
    """Determina (endpoint_type, limite) para um path de API. Função pura.

    - AI Tutor → limite de IA.
    - Auth sensível (login/registro/código/refresh) → limite estrito.
    - Demais /api/auth/* (status, me, planos, créditos...) → limite geral.
    - Resto → limite geral.
    """
    if path.startswith("/api/ai-tutor") or path.startswith("/api/v1/ai-tutor"):
        return "ai_tutor", settings.RATE_LIMIT_AI
    if path.startswith("/api/auth"):
        if path in _AUTH_SENSITIVE:
            return "auth", settings.RATE_LIMIT_AUTH
        return "general", settings.RATE_LIMIT_GENERAL
    return "general", settings.RATE_LIMIT_GENERAL


class RateLimitMiddleware(BaseHTTPMiddleware):
    """IP-based rate limiting with SQLite storage (multi-worker safe)."""

    # Static file extensions and paths to exempt
    _STATIC_EXTS = (
        '.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.gif', '.ico',
        '.woff', '.woff2', '.ttf', '.mjs', '.map', '.json', '.html', '.pdf',
    )
    _STATIC_PATHS = ('/pdfjs/', '/css/', '/js/', '/icons/', '/images/', '/fonts/')

    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path

        # Exempt health/status endpoints
        if path in ("/api/health", "/api/status", "/api/v1/health", "/api/v1/status"):
            return await call_next(request)

        # Exempt static assets
        if path.endswith(self._STATIC_EXTS) or any(path.startswith(sp) for sp in self._STATIC_PATHS):
            return await call_next(request)

        # Exempt non-API paths (frontend static files)
        if not path.startswith("/api/"):
            return await call_next(request)

        # Get client IP
        client_ip = request.client.host if request.client else "unknown"

        # Skip rate limiting for test clients
        if client_ip == "testclient":
            return await call_next(request)

        # Determine endpoint type and limit (lógica centralizada em classify_endpoint)
        endpoint_type, limit = classify_endpoint(path)
        if endpoint_type == "ai_tutor":
            # AI Tutor: rate limit por usuário (não por IP)
            identifier = _extract_user_identifier(request) or client_ip
        else:
            identifier = client_ip

        # Check rate limit
        allowed, retry_after = check_rate_limit(identifier, endpoint_type, limit)
        if not allowed:
            return Response(
                content='{"detail":"Too Many Requests. Tente novamente em alguns instantes."}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": str(retry_after)},
            )

        return await call_next(request)


def _extract_user_identifier(request: StarletteRequest) -> str | None:
    """Extract user ID from JWT token in Authorization header.

    Returns user_id string or None if no valid token.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]
    try:
        import jwt
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub") or payload.get("user_id")
        if user_id:
            return f"user:{user_id}"
    except Exception:
        pass
    return None

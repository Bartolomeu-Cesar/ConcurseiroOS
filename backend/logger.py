"""Structured JSON logger with per-request context for ConcurseiroOS.

Outputs one JSON object per line (JSON Lines format).
Automatically includes request_id and user_id from contextvars when available.
"""

import inspect
import json
import logging
import sys
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# ============================================================
# CONTEXT VARIABLES — set per-request by middleware/deps
# ============================================================

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_user_id_var: ContextVar[int] = ContextVar("user_id", default=0)


def get_request_id() -> str:
    """Get current request_id from context."""
    return _request_id_var.get()


def set_request_id(request_id: str) -> None:
    """Set request_id in context (called by middleware)."""
    _request_id_var.set(request_id)


def get_user_id_from_context() -> int:
    """Get current user_id from context."""
    return _user_id_var.get()


def set_user_id_context(user_id: int) -> None:
    """Set user_id in context (called by deps or middleware)."""
    _user_id_var.set(user_id)


# ============================================================
# STRUCTURED LOGGER
# ============================================================


class StructuredLogger:
    """JSON Lines logger with automatic context enrichment.

    Usage:
        from logger import log
        log.info("User logged in", action="login", ip="1.2.3.4")
        log.error("DB failed", error=str(e), query=sql)
    """

    def __init__(self, name: str = "concurseiro", level: str = "INFO"):
        self._name = name
        self._level = getattr(logging, level.upper(), logging.INFO)
        self._handler = sys.stdout

    def _should_log(self, level: int) -> bool:
        return level >= self._level

    def _get_caller_info(self) -> tuple[str, str]:
        """Walk up the stack to find the actual caller (skip logger internals)."""
        frame = inspect.currentframe()
        try:
            # Walk up: _get_caller_info -> _emit -> info/warning/error/debug -> caller
            caller_frame = frame
            for _ in range(4):
                if caller_frame is not None:
                    caller_frame = caller_frame.f_back
            if caller_frame:
                module = caller_frame.f_globals.get("__name__", "unknown")
                # Simplify module name: take last part
                if "." in module:
                    module = module.rsplit(".", 1)[-1]
                function = caller_frame.f_code.co_name
                return module, function
        finally:
            del frame
        return "unknown", "unknown"

    def _emit(self, level: str, message: str, **extra: Any) -> None:
        """Emit a structured JSON log line."""
        module, function = self._get_caller_info()

        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "message": message,
            "module": module,
            "function": function,
        }

        # Add context vars if present
        request_id = _request_id_var.get()
        if request_id:
            entry["request_id"] = request_id

        user_id = _user_id_var.get()
        if user_id:
            entry["user_id"] = user_id

        # Add duration_ms if provided
        if "duration_ms" in extra:
            entry["duration_ms"] = extra.pop("duration_ms")

        # Add exception info if provided
        if "exc_info" in extra:
            exc = extra.pop("exc_info")
            if exc:
                entry["exception"] = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))

        # Merge remaining extra fields
        if extra:
            entry.update(extra)

        line = json.dumps(entry, ensure_ascii=False, default=str)
        print(line, file=self._handler, flush=True)

    def info(self, message: str, **extra: Any) -> None:
        """Log at INFO level."""
        if self._should_log(logging.INFO):
            self._emit("INFO", message, **extra)

    def warning(self, message: str, **extra: Any) -> None:
        """Log at WARNING level."""
        if self._should_log(logging.WARNING):
            self._emit("WARNING", message, **extra)

    def error(self, message: str, **extra: Any) -> None:
        """Log at ERROR level."""
        if self._should_log(logging.ERROR):
            self._emit("ERROR", message, **extra)

    def debug(self, message: str, **extra: Any) -> None:
        """Log at DEBUG level."""
        if self._should_log(logging.DEBUG):
            self._emit("DEBUG", message, **extra)

    def set_level(self, level: str) -> None:
        """Change log level at runtime."""
        self._level = getattr(logging, level.upper(), logging.INFO)


# ============================================================
# MODULE-LEVEL SINGLETON
# ============================================================

log = StructuredLogger(level="INFO")

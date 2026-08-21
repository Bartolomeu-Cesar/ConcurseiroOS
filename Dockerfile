# syntax=docker/dockerfile:1

# ============================================================
# Stage 1: Builder — install Python deps in a virtual env
# ============================================================
FROM python:3.12-slim AS builder

WORKDIR /build

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt ./requirements.txt

# Install only production deps (skip dev/test and commented psycopg2)
RUN --mount=type=cache,target=/root/.cache/pip \
    grep -v '^\s*#' requirements.txt \
    | grep -v '^\s*$' \
    | grep -Ev '^(pytest|httpx)' \
    | pip install --no-compile -r /dev/stdin

# ============================================================
# Stage 2: Runtime — minimal image with only what's needed
# ============================================================
FROM python:3.12-slim AS runtime

LABEL org.opencontainers.image.title="Concurseiro OS" \
      org.opencontainers.image.description="Leitor PDF + Plano de Estudos para Concursos" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.authors="Bartholomew" \
      org.opencontainers.image.source="https://github.com/Bartholomew/LeitorPDF" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.created="2026-08-21"

# System deps for PDF OCR (tesseract + poppler) and curl for healthcheck
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser

WORKDIR /app

# Copy application code
COPY --chown=appuser:appuser backend/ ./backend/
COPY --chown=appuser:appuser frontend/ ./frontend/

# Create data directories with proper ownership
RUN mkdir -p /data/backups /data/pdfs && chown -R appuser:appuser /data

# Environment variables (same as docker-compose.yml)
ENV DB_PATH=/data/progress.db \
    BACKUP_DIR=/data/backups \
    PDF_ROOT=/data/pdfs \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

# Health check using the API endpoint from docker-compose
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ["curl", "-f", "http://localhost:8000/api/health"]

# Switch to non-root user
USER appuser

WORKDIR /app/backend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (for pdf2image/tesseract)
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Create data directories
RUN mkdir -p /data/backups /data/pdfs

# Environment
ENV DB_PATH=/data/progress.db
ENV BACKUP_DIR=/data/backups
ENV PDF_ROOT=/data/pdfs
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

WORKDIR /app/backend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

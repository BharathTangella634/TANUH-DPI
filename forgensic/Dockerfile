FROM python:3.11-slim

# ── System dependencies ────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-eng \
    libgl1 \
    libglib2.0-0 \
    libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── Python dependencies ────────────────────────────────────────────────────────
# Build context is the repo root (docker-compose: context: .)
COPY forgensic/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Application code ───────────────────────────────────────────────────────────
COPY common/ ./common/
# Copy the full forgensic package so it is importable as `forgensic.*`
COPY forgensic/ ./forgensic/

# ── Environment ───────────────────────────────────────────────────────────────
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

EXPOSE 8004

# ── Default entrypoint: API server ────────────────────────────────────────────
# The Celery worker service overrides this CMD in docker-compose:
#   celery -A forgensic.celery_app worker --loglevel=info --concurrency=2 -Q forgensic
CMD ["uvicorn", "forgensic.app.main:app", "--host", "0.0.0.0", "--port", "8004", "--workers", "2"]

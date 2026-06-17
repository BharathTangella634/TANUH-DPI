FROM python:3.11-slim

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# System deps:
#   tesseract-ocr        — OCR backend for burned-in text detection
#   poppler-utils        — PDF rasterisation support
#   libGL / libglib      — required by opencv (headless still needs libglib/libgomp)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    tesseract-ocr \
    libtesseract-dev \
    poppler-utils \
    libglib2.0-0 \
    libgl1 \
    libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching.
COPY privacy_filter/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Phase 3: shared metrics module
COPY common/ ./common/

# Copy the MedDeID engine + FastAPI service as the `privacy_filter` package.
# Build context is the repo root (see docker-compose: context: .).
COPY privacy_filter/__init__.py   ./privacy_filter/__init__.py
COPY privacy_filter/celery_app.py ./privacy_filter/celery_app.py
COPY privacy_filter/tasks.py      ./privacy_filter/tasks.py
COPY privacy_filter/app/          ./privacy_filter/app/
COPY privacy_filter/cli/          ./privacy_filter/cli/
COPY privacy_filter/detectors/    ./privacy_filter/detectors/
COPY privacy_filter/loaders/      ./privacy_filter/loaders/
COPY privacy_filter/metadata/     ./privacy_filter/metadata/
COPY privacy_filter/pipeline/     ./privacy_filter/pipeline/
COPY privacy_filter/redactors/    ./privacy_filter/redactors/
COPY privacy_filter/registry/     ./privacy_filter/registry/
COPY privacy_filter/savers/       ./privacy_filter/savers/
COPY privacy_filter/schemas/      ./privacy_filter/schemas/
COPY privacy_filter/utils/        ./privacy_filter/utils/
COPY privacy_filter/validators/   ./privacy_filter/validators/

# Local data dirs (uploads + redacted outputs) for the local storage backend.
ENV LOCAL_DATA_DIR=/tmp/data
RUN mkdir -p /tmp/data/uploads /tmp/data/redacted

EXPOSE 8003

CMD ["uvicorn", "privacy_filter.app.main:app", "--host", "0.0.0.0", "--port", "8003", "--workers", "1"]

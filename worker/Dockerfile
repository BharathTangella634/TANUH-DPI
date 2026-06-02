FROM python:3.11-slim

WORKDIR /app

# System deps (docling, opencv, tesseract, poppler)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    gcc \
    g++ \
    libgl1 \
    libglib2.0-0 \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

# Install pdf2nhcx and pdf2abdm Python deps.
# CPU-only torch first (docling pulls torch; default wheel bundles ~3-4 GB of
# unused CUDA libs). Shared pip cache mount → torch fetched at most once.
COPY pdf2nhcx/requirements.txt /tmp/nhcx-requirements.txt
COPY pdf2abdm/requirements.txt /tmp/abdm-requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision && \
    pip install -r /tmp/nhcx-requirements.txt && \
    pip install -r /tmp/abdm-requirements.txt

# Copy shared common module
COPY common/ ./common/

# Copy pdf2nhcx module
COPY pdf2nhcx/__init__.py      ./pdf2nhcx/__init__.py
COPY pdf2nhcx/app/             ./pdf2nhcx/app/
COPY pdf2nhcx/utils/           ./pdf2nhcx/utils/
COPY pdf2nhcx/rulebooks_updated/ ./pdf2nhcx/rulebooks_updated/
COPY pdf2nhcx/tasks.py         ./pdf2nhcx/tasks.py

# Copy pdf2abdm module
COPY pdf2abdm/__init__.py      ./pdf2abdm/__init__.py
COPY pdf2abdm/app/             ./pdf2abdm/app/
COPY pdf2abdm/utils/           ./pdf2abdm/utils/
COPY pdf2abdm/rulebooks_updated/ ./pdf2abdm/rulebooks_updated/
COPY pdf2abdm/tasks.py         ./pdf2abdm/tasks.py

# Both services import via their own namespaced paths:
#   pdf2nhcx.utils.*  and  pdf2abdm.utils.*
# No bare ./utils/ shim needed — removed to prevent abdm overwriting nhcx utils.

# privacy-filter is deployed on Cloud Run — no local copy needed

ENV PYTHONPATH=/app

# Two services, 2 concurrent task slots
CMD ["celery", "-A", "common.celery_app", "worker", \
     "--loglevel=info", "--concurrency=2", \
     "-I", "pdf2abdm.tasks,pdf2nhcx.tasks"]

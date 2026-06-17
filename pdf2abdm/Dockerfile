FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required by pymupdf, docling, and opencv
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

COPY pdf2abdm/requirements.txt .
# Install CPU-only torch first. docling depends on torch; the default PyPI wheel
# bundles ~3-4 GB of NVIDIA CUDA libraries this CPU-only service never uses.
# The CPU wheel (~190 MB) comes from PyTorch's CDN. The pip cache mount persists
# downloads across retries and is shared with pdf2nhcx (identical torch), so the
# wheel is fetched at most once for the whole stack.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r requirements.txt

COPY common/ ./common/
COPY scripts/fetch_validator_jar.py ./scripts/fetch_validator_jar.py
COPY scripts/entrypoint-abdm.sh ./scripts/entrypoint-abdm.sh
RUN chmod +x ./scripts/entrypoint-abdm.sh
COPY pdf2abdm/__init__.py ./pdf2abdm/__init__.py
COPY pdf2abdm/app/ ./pdf2abdm/app/
# Copy utils to both locations:
#   /app/pdf2abdm/utils/ — for 'from pdf2abdm.utils.x import ...'
#   /app/utils/          — for bare 'from utils.x import ...' in main.py and tasks.py
COPY pdf2abdm/utils/ ./pdf2abdm/utils/
COPY pdf2abdm/utils/ ./utils/
COPY pdf2abdm/rulebooks_updated/ ./pdf2abdm/rulebooks_updated/
COPY pdf2abdm/tasks.py ./pdf2abdm/tasks.py

# Set PYTHONPATH so imports work
ENV PYTHONPATH=/app

EXPOSE 8000

ENTRYPOINT ["./scripts/entrypoint-abdm.sh"]
CMD ["uvicorn", "pdf2abdm.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--timeout-keep-alive", "1500"]

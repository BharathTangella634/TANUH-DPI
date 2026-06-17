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

COPY pdf2nhcx/requirements.txt .
# Install CPU-only torch first. docling depends on torch; the default PyPI wheel
# bundles ~3-4 GB of NVIDIA CUDA libraries this CPU-only service never uses.
# The CPU wheel (~190 MB) comes from PyTorch's CDN. The pip cache mount persists
# downloads across retries and is shared with pdf2abdm (identical torch), so the
# wheel is fetched at most once for the whole stack.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
    && pip install -r requirements.txt

COPY common/ ./common/
COPY scripts/fetch_validator_jar.py ./scripts/fetch_validator_jar.py
COPY scripts/entrypoint-abdm.sh ./scripts/entrypoint-abdm.sh
RUN chmod +x ./scripts/entrypoint-abdm.sh
COPY pdf2nhcx/__init__.py ./pdf2nhcx/__init__.py
COPY pdf2nhcx/app/ ./pdf2nhcx/app/
# Copy utils to both locations:
#   /app/pdf2nhcx/utils/ — for 'from pdf2nhcx.utils.x import ...'
#   /app/utils/          — for bare 'from utils.x import ...' in main.py and tasks.py
COPY pdf2nhcx/utils/ ./pdf2nhcx/utils/
COPY pdf2nhcx/utils/ ./utils/
COPY pdf2nhcx/rulebooks_updated/ ./pdf2nhcx/rulebooks_updated/
COPY pdf2nhcx/tasks.py ./pdf2nhcx/tasks.py

# Set PYTHONPATH so imports work
ENV PYTHONPATH=/app

EXPOSE 8001

ENTRYPOINT ["./scripts/entrypoint-abdm.sh"]
CMD ["uvicorn", "pdf2nhcx.app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "2", "--timeout-keep-alive", "1500"]

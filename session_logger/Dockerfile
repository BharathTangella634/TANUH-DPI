FROM python:3.11-slim

WORKDIR /app

# Minimal system deps for PyMySQL
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY session_logger/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY common/ ./common/
COPY session_logger/__init__.py          ./session_logger/__init__.py
COPY session_logger/app/                 ./session_logger/app/

# Set PYTHONPATH so package imports resolve correctly
ENV PYTHONPATH=/app

EXPOSE 8002

CMD ["uvicorn", "session_logger.app.main:app", "--host", "0.0.0.0", "--port", "8002", "--timeout-keep-alive", "300"]

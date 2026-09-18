FROM python:3.11-slim

WORKDIR /app

# Build context is the repo root (see docker-compose*.yml) so common/secrets.py
# can be shared with the app services rather than duplicated here. That module
# resolves REDIS_PASSWORD_SECRET from Secret Manager and injects the password
# into REDIS_URL — Memorystore has AUTH enabled, so the exporter cannot read
# queue depths without it.
COPY monitoring/queue-exporter/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Only the secrets helper is copied; the rest of common/ pulls in FastAPI and
# Celery, which this exporter has no use for.
COPY common/__init__.py common/secrets.py ./common/

COPY monitoring/queue-exporter/queue_exporter.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 9101

CMD ["python", "queue_exporter.py"]

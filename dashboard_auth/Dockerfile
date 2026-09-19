FROM python:3.11-slim

WORKDIR /app

COPY dashboard_auth/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY dashboard_auth/__init__.py ./dashboard_auth/__init__.py
COPY dashboard_auth/app/        ./dashboard_auth/app/

ENV PYTHONPATH=/app

EXPOSE 8005

CMD ["uvicorn", "dashboard_auth.app.main:app", "--host", "0.0.0.0", "--port", "8005"]

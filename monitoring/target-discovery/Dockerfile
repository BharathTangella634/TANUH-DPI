FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY discover_targets.py .

CMD ["python", "discover_targets.py"]

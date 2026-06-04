FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY queue_exporter.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 9101

CMD ["python", "queue_exporter.py"]

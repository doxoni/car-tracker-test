# -*- coding: utf-8 -*-
# Dockerfile для car-tracker — Render / VPS
FROM python:3.12-slim

WORKDIR /app

# Установить зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Скопировать код
COPY app/ ./app/
COPY bot/ ./bot/
COPY migrations/ ./migrations/
COPY wsgi.py .
COPY Procfile .

EXPOSE 5000

CMD ["gunicorn", "--workers", "1", "--threads", "4", "--timeout", "120", "--bind", "0.0.0.0:5000", "wsgi:app"]

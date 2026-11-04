# -*- coding: utf-8 -*-
# Dockerfile для car-tracker — Render / VPS
FROM python:3.12-slim

WORKDIR /app

# Установить зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копировать код
COPY app/ ./app/
COPY static/ ./static/
COPY templates/ ./templates/
COPY migrations/ ./migrations/
COPY Procfile .

EXPOSE 5000

CMD ["python", "app/main.py"]
# -*- coding: utf-8 -*-
# Makefile для car-tracker — удобные команды
# Использование: make <цель>

.PHONY: help install run test migrate-up migrate-down lint fmt clean

# Переменные
PYTHON = python3
PIP = pip3
APP = app/main.py
DB = cars.db

# Цель по умолчанию
help:
	@echo "Доступные цели:"
	@echo "  install     - установить зависимости"
	@echo "  run         - запустить сервер разработки"
	@echo "  migrate-up  - применить миграции"
	@echo "  migrate-down - откатить последнюю миграцию"
	@echo "  lint        - проверить стиль кода (flake8)"
	@echo "  fmt         - отформатировать код (black)"
	@echo "  clean       - удалить временные файлы"

# Установка зависимостей
install:
	$(PIP) install -r requirements.txt

# Запуск сервера разработки
run:
	$(PYTHON) $(APP)

# Миграции
migrate-up:
	alembic upgrade head

migrate-down:
	alembic downgrade -1

# Линтер
lint:
	flake8 app/ migrations/ 2>/dev/null || true

# Форматирование
fmt:
	black app/ migrations/ 2>/dev/null || true

# Очистка
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -f $(DB) 2>/dev/null || true

# Тесты (пока нет)
test:
	@echo "Тесты пока не настроены. Запустите вручную: python app/main.py"
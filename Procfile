# -*- coding: utf-8 -*-
# Procfile для Render (используется если не используется Dockerfile)
web: gunicorn --workers 1 --threads 4 --timeout 120 --bind 0.0.0.0:$PORT wsgi:app

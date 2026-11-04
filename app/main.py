# -*- coding: utf-8 -*-
""" Точка входа для car-tracker backend.

Запуск: `python app/main.py`
"""

from . import create_app


application = create_app()


def main():
    application.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
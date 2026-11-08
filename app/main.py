# -*- coding: utf-8 -*-
""" Точка входа для car-tracker backend.

Запуск: `python app/main.py`
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app


application = create_app()


def main():
    application.run(host="0.0.0.0", port=5000)


if __name__ == "__main__":
    main()
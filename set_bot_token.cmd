@echo off
REM Вписать токен бота и задеплоить сервис на Render.
REM Спросит токен от @BotFather, сохранит его в render_env.txt
REM (файл в .gitignore) и запустит деплой.
cd /d "%~dp0"
python tools\set_bot_token.py
pause

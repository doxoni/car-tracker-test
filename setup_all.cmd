@echo off
REM setup_all.cmd - полная настройка car-tracker: облачная база + деплой на Render.
REM
REM Запуск (двойной клик или из PowerShell):
REM     .\setup_all.cmd 123456789
REM
REM Число - это твой Telegram ID, из него делается админ (уровень 3).
REM
REM Что делает:
REM   1. Создаёт облачную базу PostgreSQL (Google Cloud SQL, а если нет
REM      биллинга Google - Neon, там карта не нужна).
REM   2. Создаёт/обновляет сервис на Render, ставит DATABASE_URL, деплоит.
REM   3. Создаёт админа в базе.
REM
REM Подготовь один раз:
REM   - render_key.txt   - ключ Render API (https://dashboard.render.com/account/api-keys)
REM   - render_env.txt   - TELEGRAM_TOKEN, ADMIN_TELEGRAM_ID, WHITELISTED_TELEGRAM_IDS

setlocal
cd /d "%~dp0"

echo ============================================================
echo  car-tracker setup: облачная база + Render
echo ============================================================
echo.

if "%1"=="" (
  powershell -ExecutionPolicy Bypass -File "%~dp0setup_db.ps1"
) else (
  powershell -ExecutionPolicy Bypass -File "%~dp0setup_db.ps1"
)
if errorlevel 2 goto :no_db
if errorlevel 1 goto :error

echo.
echo ============================================================
echo  Deploying to Render
echo ============================================================
echo.
if "%1"=="" (
  python "%~dp0deploy_render.py"
) else (
  python "%~dp0deploy_render.py" --telegram-id %1
)
if errorlevel 1 goto :error

echo.
echo ============================================================
echo  DONE. Check the Render dashboard for the service URL.
echo ============================================================
goto :end

:no_db
echo.
echo Database was not set up - see the steps above.
echo Finish them and run this command again.
goto :end

:error
echo.
echo Something failed - see the messages above.

:end
endlocal
pause

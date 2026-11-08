@echo off
REM setup_all.cmd - full car-tracker setup: Cloud SQL database + Render deploy.
REM
REM Run (double-click, or from PowerShell):
REM     .\setup_all.cmd 123456789
REM
REM The number is your Telegram ID - it becomes the admin (level 3).
REM
REM What it does:
REM   1. Creates the database in Google Cloud SQL (needs a Google billing account).
REM   2. Creates/updates the service on Render, sets DATABASE_URL, deploys.
REM   3. Creates the admin account in the database.
REM
REM Prepare once:
REM   - render_key.txt   - Render API key (https://dashboard.render.com/account/api-keys)
REM   - render_env.txt   - TELEGRAM_TOKEN, ADMIN_TELEGRAM_ID, WHITELISTED_TELEGRAM_IDS

setlocal
cd /d "%~dp0"

echo ============================================================
echo  car-tracker setup: Google Cloud SQL + Render
echo ============================================================
echo.

if "%1"=="" (
  powershell -ExecutionPolicy Bypass -File "%~dp0setup_cloud_sql.ps1"
) else (
  powershell -ExecutionPolicy Bypass -File "%~dp0setup_cloud_sql.ps1" -TelegramId %1
)
if errorlevel 2 goto :no_billing
if errorlevel 1 goto :error

echo.
echo ============================================================
echo  DONE. Check the Render dashboard for the service URL.
echo ============================================================
goto :end

:no_billing
echo.
echo A Google Cloud billing account is required - see the steps above.
echo Create it and run this command again.
goto :end

:error
echo.
echo Something failed - see the messages above.

:end
endlocal
pause

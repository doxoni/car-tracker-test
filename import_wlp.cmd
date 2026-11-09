@echo off
REM Загрузить машины из архива Wialon (.wlp) в облачную базу.
REM Использование: import_wlp.cmd "C:\Users\koval\Downloads\Объекты (1).zip"
setlocal
cd /d "%~dp0"
if "%~1"=="" (
    echo Укажи путь к архиву .zip с файлами .wlp
    echo Пример: import_wlp.cmd "C:\Users\koval\Downloads\Объекты (1).zip"
    exit /b 1
)
if not exist ".db_connection.txt" (
    echo Не найден файл .db_connection.txt - сначала настрой облачную базу
    exit /b 1
)
for /f "usebackq tokens=1,* delims==" %%A in (".db_connection.txt") do (
    if /i "%%A"=="DATABASE_URL" set "DATABASE_URL=%%B"
)
if "%DATABASE_URL%"=="" (
    echo В .db_connection.txt нет строки DATABASE_URL
    exit /b 1
)
python -m app.import_wlp --zip "%~1"
exit /b %errorlevel%

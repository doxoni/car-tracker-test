@echo off
REM set_level.cmd - выдать уровень доступа пользователю car-tracker.
REM
REM Запуск (двойной клик или из PowerShell):
REM     .\set_level.cmd 123456789 1
REM
REM 123456789 - Telegram ID человека, 1 - уровень:
REM   1 - водитель, 2 - оператор, 3 - суперадмин (все права).
REM
REM Строку подключения скрипт берёт сам из .db_connection.txt.

setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo.
  echo Укажи Telegram ID и уровень, например:
  echo     .\set_level.cmd 123456789 1
  echo.
  echo Уровни: 1 - водитель, 2 - оператор, 3 - суперадмин.
  goto :end
)

python "%~dp0create_admin.py" %1 %2 %3
if errorlevel 1 (
  echo.
  echo Не получилось выдать уровень - смотри сообщение выше.
)

:end
endlocal
pause

@echo off
REM Управление монитором UptimeRobot (дневной пинг, ночная пауза).
REM
REM Запуск (двойной клик или из PowerShell):
REM     .\uptime_monitor.cmd setup    - создать монитор
REM     .\uptime_monitor.cmd status   - показать состояние
REM     .\uptime_monitor.cmd pause    - поставить на паузу
REM     .\uptime_monitor.cmd start    - снять с паузы
REM     .\uptime_monitor.cmd auto     - включить/выключить по времени
REM
REM Если файла uptime_key.txt нет - скрипт спросит ключ и сохранит его.
REM Ключ берётся в UptimeRobot: Integrations -> API -> Create API key.

setlocal EnableDelayedExpansion
cd /d "%~dp0"

if "%~1"=="" (
  echo.
  echo Укажи команду: setup, status, pause, start или auto
  echo Например: .\uptime_monitor.cmd setup
  echo.
  goto :end
)

if not exist "uptime_key.txt" (
  if "%UPTIME_API_KEY%"=="" (
    echo.
    echo Ключ UptimeRobot ещё не сохранён.
    echo Возьми его в UptimeRobot: Integrations -^> API -^> Create API key
    echo и вставь сюда одной строкой (введи и нажми Enter):
    echo.
    set /p "UPTIME_KEY=Ключ: "
    if "!UPTIME_KEY!"=="" (
      echo Ключ не введён - монитор настроить не получилось.
      goto :end
    )
    echo !UPTIME_KEY!> uptime_key.txt
    echo Ключ сохранён в uptime_key.txt
    echo.
  )
)

python "%~dp0uptime_monitor.py" %1
if errorlevel 1 (
  echo.
  echo Не получилось выполнить команду - смотри сообщение выше.
)

:end
endlocal
pause

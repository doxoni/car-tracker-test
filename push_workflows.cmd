@echo off
rem Заливает workflow-файлы ночной паузы в ветку test.
rem Нужен токен GitHub со scope repo + workflow.
rem Порядок: создать classic PAT на https://github.com/settings/tokens
rem (галочки repo и workflow), положить его в файл github_token.txt
rem рядом с этим скриптом и запустить push_workflows.cmd.

cd /d "%~dp0"

if not exist "github_token.txt" (
    echo Файла github_token.txt нет.
    echo Создай токен на https://github.com/settings/tokens с галочками repo и workflow
    echo и положи его в файл github_token.txt ^(одна строка, без пробелов^).
    pause
    exit /b 1
)

set /p TOKEN=<github_token.txt
if "%TOKEN%"=="" (
    echo Файл github_token.txt пустой.
    pause
    exit /b 1
)

set TOKEN=%TOKEN: =%

git push https://%TOKEN%@github.com/doxoni/car-tracker-test.git HEAD:test
if errorlevel 1 (
    echo.
    echo Не получилось залить. Проверь, что в токене есть scope workflow.
    pause
    exit /b 1
)

echo.
echo Готово: workflow-файлы залиты в ветку test.
pause

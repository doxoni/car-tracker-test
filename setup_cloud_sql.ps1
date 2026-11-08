# -*- coding: utf-8 -*-
# setup_cloud_sql.ps1 — создаёт PostgreSQL в Google Cloud SQL для car-tracker.
#
# Запуск (PowerShell в папке проекта):
#   powershell -ExecutionPolicy Bypass -File setup_cloud_sql.ps1
#
# Что делает:
#   1. Включает Cloud SQL API в проекте Google Cloud
#   2. Создаёт инстанс cars-tracker-db (free tier: db-f1-micro)
#   3. Создаёт базу cars и пользователя car_tracker
#   4. Разрешает подключения из интернета (Render обращается по публичному IP)
#   5. Сохраняет строку подключения в .cloudsql_connection.txt
#
# После запуска строку из .cloudsql_connection.txt вставить в Render Dashboard
# как переменную DATABASE_URL.

$ErrorActionPreference = "Stop"

$PROJECT   = "car-tracker-test"
$INSTANCE  = "cars-tracker-db"
$DB_NAME   = "cars"
$DB_USER   = "car_tracker"
$DB_PASS   = "Ct_" + [guid]::NewGuid().ToString("N").Substring(0,20)
$REGION    = "us-central1"
$TIER      = "db-f1-micro"
$DB_VERSION= "POSTGRES_15"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# ---------- 1. Проверка gcloud ----------
Step "Проверка gcloud"
$gcloud = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloud) {
    $candidates = @(
        "$env:LOCALAPPDATA\Google\Cloud SDK\bin\gcloud.cmd",
        "C:\Program Files (x86)\Google\Cloud SDK\bin\gcloud.cmd",
        "C:\Program Files\Google\Cloud SDK\bin\gcloud.cmd"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $gcloud = $c; break }
    }
}
if (-not $gcloud) {
    Write-Error "gcloud не найден. Установи: winget install --id Google.CloudSDK"
}
Write-Host "gcloud: $gcloud"

# ---------- 2. Авторизация и проект ----------
Step "Авторизация"
& $gcloud auth list 2>&1 | Out-String | Write-Host
& $gcloud config set project $PROJECT 2>&1 | Out-String | Write-Host

Step "Включение Cloud SQL API"
& $gcloud services enable sqladmin.googleapis.com --project=$PROJECT 2>&1 | Out-String | Write-Host

# ---------- 3. Инстанс ----------
Step "Создание инстанса $INSTANCE"
$exists = (& $gcloud sql instances describe $INSTANCE --project=$PROJECT --format="value(name)" 2>$null)
if ($exists -eq $INSTANCE) {
    Write-Host "Инстанс уже существует — пропускаем создание."
} else {
    & $gcloud sql instances create $INSTANCE `
        --database-version=$DB_VERSION `
        --tier=$TIER `
        --region=$REGION `
        --availability-type=ZONAL `
        --assign-ip `
        --project=$PROJECT 2>&1 | Out-String | Write-Host
}

# ---------- 4. Публичный IP для Render ----------
Step "Назначение статического IP"
$ipName = "$INSTANCE-ip"
$hasIp = (& $gcloud sql addresses list --project=$PROJECT --filter="name~$ipName" --format="value(name)" 2>$null)
if (-not $hasIp) {
    & $gcloud sql addresses create $ipName --region=$REGION --project=$PROJECT 2>&1 | Out-String | Write-Host
}
& $gcloud sql instances patch $INSTANCE --assign-ip $ipName --project=$PROJECT 2>&1 | Out-String | Write-Host

# ---------- 5. Разрешённые сети (Render использует динамические IP) ----------
Step "Разрешение подключений из интернета"
& $gcloud sql instances patch $INSTANCE --authorized-networks=0.0.0.0/0 --project=$PROJECT 2>&1 | Out-String | Write-Host

# ---------- 6. База и пользователь ----------
Step "Создание базы $DB_NAME и пользователя $DB_USER"
& $gcloud sql databases create $DB_NAME --instance=$INSTANCE --project=$PROJECT 2>&1 | Out-String | Write-Host
& $gcloud sql users create $DB_USER --instance=$INSTANCE --password=$DB_PASS --project=$PROJECT 2>&1 | Out-String | Write-Host

# ---------- 7. Строка подключения ----------
Step "Получение публичного IP"
$ip = (& $gcloud sql instances describe $INSTANCE --project=$PROJECT --format="value(ipAddresses)" 2>$null)
if (-not $ip) {
    Write-Error "Не удалось получить IP инстанса. Проверь: gcloud sql instances describe $INSTANCE"
}
$ip = ($ip -split ";" | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" } | Select-Object -First 1)

$url = "postgresql://${DB_USER}:${DB_PASS}@${ip}:5432/${DB_NAME}?sslmode=require"
$outFile = Join-Path $PSScriptRoot ".cloudsql_connection.txt"
@(
    "# Подключение к Google Cloud SQL — car-tracker",
    "# Скопируй строку DATABASE_URL ниже в Render Dashboard -> Environment",
    "DATABASE_URL=$url",
    "",
    "DB_HOST=$ip",
    "DB_PORT=5432",
    "DB_NAME=$DB_NAME",
    "DB_USER=$DB_USER",
    "DB_PASSWORD=$DB_PASS",
    "DB_SSLMODE=require"
) | Set-Content -Path $outFile -Encoding UTF8

Write-Host ""
Write-Host "Готово. Строка подключения сохранена в: $outFile" -ForegroundColor Green
Write-Host ""
Write-Host "DATABASE_URL=$url" -ForegroundColor Yellow
Write-Host ""
Write-Host "Дальше:" -ForegroundColor Cyan
Write-Host "  1. Открой Render Dashboard -> твой сервис -> Environment"
Write-Host "  2. Добавь DATABASE_URL = значение выше"
Write-Host "  3. Нажми Save & Deploy"

# setup_db.ps1 - создаёт облачную базу данных PostgreSQL для car-tracker.
#
# Запуск в PowerShell из папки проекта:
#   powershell -ExecutionPolicy Bypass -File setup_db.ps1
#
# Что делает:
#   1. Если файл .db_connection.txt уже есть - ничего не создаёт, выходит.
#   2. Проверяет биллинг-аккаунт Google Cloud. Если он есть - создаёт
#      инстанс Cloud SQL (бесплатный тариф db-f1-micro) и базу в нём.
#   3. Если биллинга нет - предлагает Neon: бесплатный PostgreSQL,
#      карта не нужна. Пользователь копирует строку подключения из
#      консоли Neon и вставляет её прямо в это окно.
#   4. Сохраняет строку подключения в .db_connection.txt.
#
# NOTE: файл сохранён в UTF-8 с BOM - так Windows PowerShell 5.1 (которым
# запускается setup_all.cmd) правильно читает русский текст.

param(
    [switch]$Force
)

$ErrorActionPreference = "Continue"

$PROJECT    = "car-tracker-261020"
$INSTANCE   = "cars-tracker-db"
$DB_NAME    = "cars"
$DB_USER    = "car_tracker"
$DB_PASS    = "Ct_" + [guid]::NewGuid().ToString("N").Substring(0,20)
$REGION     = "us-central1"     # единственный регион с бесплатным db-f1-micro
$TIER       = "db-f1-micro"      # free tier: 1 vCPU, 0.75 ГБ RAM
$DB_VERSION = "POSTGRES_15"
$STORAGE_GB = 10                 # free tier: 10 ГБ
$CONSOLE_BILLING_URL = "https://console.cloud.google.com/billing/create?project=$PROJECT"
$NEON_URL = "https://console.neon.tech/app"
$NEON_KEYS_URL = "https://console.neon.tech/app/settings/api-keys"

$outFile = Join-Path $PSScriptRoot ".db_connection.txt"

function Step($msg) { Write-Host ""; Write-Host "=== $msg ===" -ForegroundColor Cyan }
function Info($msg) { Write-Host $msg }

# Run gcloud with given arguments, print its output, fail on non-zero exit code.
# NOTE: parameter is named GcloudArgs (NOT $Args - that name is reserved by PowerShell).
# WARNING-строки gcloud отбрасываются: иначе они попадают в разбор ответа.
function Invoke-Gcloud {
    param([string[]]$GcloudArgs, [switch]$AllowFail)
    $out = & $script:GcloudExe @GcloudArgs 2>&1
    $code = $LASTEXITCODE
    $lines = @($out | ForEach-Object { "$_" } | Where-Object { $_ -notlike "WARNING:*" -and $_ -notlike "The following filter keys*" })
    $text = ($lines -join "`n").Trim()
    if ($text) { Write-Host $text }
    if ($code -ne 0 -and -not $AllowFail) {
        throw "gcloud failed (exit $code): $($GcloudArgs -join ' ')"
    }
    return $text
}

# ---------- 0. Уже настроено? ----------
if ((Test-Path $outFile) -and -not $Force) {
    $existing = Get-Content $outFile -Encoding UTF8 | Where-Object { $_ -like "DATABASE_URL=*" } | Select-Object -First 1
    if ($existing) {
        Write-Host ""
        Write-Host "База уже настроена (.db_connection.txt). Ничего не делаю." -ForegroundColor Green
        Write-Host "Пересоздать с нуля: powershell -ExecutionPolicy Bypass -File setup_db.ps1 -Force"
        exit 0
    }
}

# ---------- 1. Locate gcloud ----------
Step "Checking gcloud"
$GcloudExe = $null
$candidates = @(
    "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
    "$env:LOCALAPPDATA\Google\Cloud SDK\bin\gcloud.cmd",
    "C:\Program Files (x86)\Google\Cloud SDK\bin\gcloud.cmd",
    "C:\Program Files\Google\Cloud SDK\bin\gcloud.cmd"
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $GcloudExe = $c; break }
}
if (-not $GcloudExe) {
    $cmd = Get-Command gcloud.cmd -CommandType Application -ErrorAction SilentlyContinue
    if ($cmd) { $GcloudExe = $cmd.Source }
}
if (-not $GcloudExe) {
    Write-Host "gcloud не найден - переходим на Neon (карта не нужна)." -ForegroundColor Yellow
    $GcloudExe = $null
} else {
    Write-Host "gcloud: $GcloudExe"
    $script:GcloudExe = $GcloudExe
}

# ---------- 2. Billing account ----------
# Cloud SQL нельзя создать без биллинг-аккаунта, а Google требует
# привязанный способ оплаты даже для бесплатного тарифа. Если счёта
# нет - предлагаем Neon, там карта не нужна.
$hasBilling = $false
$billingAccount = ""
if ($GcloudExe) {
    Step "Checking billing account"
    $accounts = (Invoke-Gcloud -GcloudArgs @("billing","accounts","list","--format=value(name)") -AllowFail).Trim()
    # gcloud печатает "Listed 0 items." вместо пустого вывода - это не счёт
    $accountLine = @($accounts -split "`n" | Where-Object { $_ -match "^billingAccounts/" } | Select-Object -First 1)
    if ($accountLine) {
        $billingAccount = $accountLine[0].Trim()
        $hasBilling = $true
        Write-Host "Billing account: $billingAccount"
    } else {
        Write-Host "Биллинг-аккаунта Google нет." -ForegroundColor Yellow
    }
}

if ($hasBilling) {
    # ---------- 3. Google Cloud SQL ----------
    $linked = (Invoke-Gcloud -GcloudArgs @("billing","projects","describe",$PROJECT,"--format=value(billingAccountName)") -AllowFail).Trim()
    if ($linked -ne $billingAccount) {
        Step "Linking project $PROJECT to $billingAccount"
        Invoke-Gcloud -GcloudArgs @("billing","projects","link",$PROJECT,"--billing-account=$billingAccount") | Out-Null
    } else {
        Write-Host "Project is already linked to $billingAccount"
    }

    Step "Enabling Cloud SQL Admin API"
    Invoke-Gcloud -GcloudArgs @("services", "enable", "sqladmin.googleapis.com", "--project=$PROJECT", "--quiet") | Out-Null
    Invoke-Gcloud -GcloudArgs @("config", "set", "project", $PROJECT) | Out-Null

    # NOTE: gcloud sql addresses is missing in this SDK build, so the instance
    # gets its built-in public IP (--assign-ip). The IP stays the same for the
    # whole life of the instance.
    # Free tier: shared CPU, 10 GB storage, no automatic backups (they are
    # billed separately), no storage auto-increase.
    Step "Creating instance $INSTANCE"
    $exists = Invoke-Gcloud -GcloudArgs @("sql","instances","describe",$INSTANCE,"--project=$PROJECT","--format=value(name)") -AllowFail
    if ($exists -match $INSTANCE) {
        Write-Host "Instance already exists - patching instead."
        Invoke-Gcloud -GcloudArgs @("sql","instances","patch",$INSTANCE,
            "--assign-ip",
            "--authorized-networks=0.0.0.0/0",
            "--no-backup",
            "--no-storage-auto-increase",
            "--storage-size=$STORAGE_GB",
            "--project=$PROJECT") | Out-Null
    } else {
        Invoke-Gcloud -GcloudArgs @("sql","instances","create",$INSTANCE,
            "--database-version=$DB_VERSION",
            "--tier=$TIER",
            "--region=$REGION",
            "--availability-type=ZONAL",
            "--assign-ip",
            "--no-backup",
            "--no-storage-auto-increase",
            "--storage-size=$STORAGE_GB",
            "--project=$PROJECT") | Out-Null
        Invoke-Gcloud -GcloudArgs @("sql","instances","patch",$INSTANCE,
            "--authorized-networks=0.0.0.0/0",
            "--project=$PROJECT") | Out-Null
    }

    Step "Waiting for the instance to become RUNNABLE"
    $state = ""
    for ($i = 1; $i -le 60; $i++) {
        $state = (Invoke-Gcloud -GcloudArgs @("sql","instances","describe",$INSTANCE,"--project=$PROJECT","--format=value(state)") -AllowFail).Trim()
        Write-Host "  state: $state"
        if ($state -eq "RUNNABLE") { break }
        if ($state -eq "FAILED") { throw "Instance creation failed. Check: gcloud sql operations list --instance=$INSTANCE --project=$PROJECT" }
        Start-Sleep -Seconds 10
    }
    if ($state -ne "RUNNABLE") { throw "Instance is not ready (state: $state)" }

    Step "Creating database $DB_NAME and user $DB_USER"
    Invoke-Gcloud -GcloudArgs @("sql","databases","create",$DB_NAME,"--instance=$INSTANCE","--project=$PROJECT") -AllowFail | Out-Null
    # set-password always runs, so a re-run keeps the password in sync with the saved file
    Invoke-Gcloud -GcloudArgs @("sql","users","set-password",$DB_USER,"--instance=$INSTANCE","--password=$DB_PASS","--project=$PROJECT") -AllowFail | Out-Null
    Invoke-Gcloud -GcloudArgs @("sql","users","create",$DB_USER,"--instance=$INSTANCE","--password=$DB_PASS","--project=$PROJECT") -AllowFail | Out-Null

    Step "Reading public IP"
    $ipRaw = Invoke-Gcloud -GcloudArgs @("sql","instances","describe",$INSTANCE,"--project=$PROJECT","--format=value(ipAddresses)")
    $m = [regex]::Match($ipRaw, "(\d+\.\d+\.\d+\.\d+)")
    if (-not $m.Success) { throw "Could not read instance IP from: $ipRaw" }
    $ip = $m.Groups[1].Value

    $url = "postgresql://${DB_USER}:${DB_PASS}@${ip}:5432/${DB_NAME}?sslmode=require"
    @(
        "# Cloud SQL connection - car-tracker",
        "DATABASE_URL=$url",
        "",
        "DB_HOST=$ip",
        "DB_PORT=5432",
        "DB_NAME=$DB_NAME",
        "DB_USER=$DB_USER",
        "DB_PASSWORD=$DB_PASS",
        "DB_SSLMODE=require"
    ) | Set-Content -Path $outFile -Encoding UTF8
} else {
    # ---------- 3. Neon (без карты) ----------
    # Если есть ключ Neon - проект создаётся сам, через API.
    $neonKeyFile = Join-Path $PSScriptRoot "neon_key.txt"
    if (Test-Path $neonKeyFile) {
        Step "Создаём базу в Neon"
        $env:NEON_API_KEY = ((Get-Content $neonKeyFile -Raw).Trim())
        python (Join-Path $PSScriptRoot "setup_neon.py")
        $neonCode = $LASTEXITCODE
        if (Test-Path Env:\NEON_API_KEY) { Remove-Item Env:\NEON_API_KEY }
        if ($neonCode -ne 0) { exit $neonCode }
    } else {
        Step "Настройка базы в Neon"
        Write-Host ""
        Write-Host "Google Cloud требует карту для биллинга, а она не нужна для Neon:" -ForegroundColor Cyan
        Write-Host "Neon - бесплатный PostgreSQL, карта не требуется, база не засыпает насовсем." -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Сделай один раз в браузере (2 минуты):" -ForegroundColor Cyan
        Write-Host "  1. Открой: $NEON_URL"
        Write-Host "  2. Войди через Google или GitHub (карта не спрашивается)."
        Write-Host "  3. Создай проект: имя cars, регион - Europe (Frankfurt)."
        Write-Host "  4. На странице проекта найди Connection string и скопируй его."
        Write-Host ""
        Write-Host "ВАЖНО: бери обычный (direct) адрес, без -pooler в имени хоста." -ForegroundColor Yellow
        Write-Host ""
        Write-Host "Если хочешь, чтобы дальше всё делалось само, создай API-ключ:" -ForegroundColor Cyan
        Write-Host "  https://console.neon.tech/app/settings/api-keys -> Create API key"
        Write-Host "  и сохрани его (одна строка, начиная с napi_) в файл neon_key.txt"
        Write-Host "  рядом с этим скриптом. Тогда проект создастся сам."
        Write-Host ""
        try { Start-Process $NEON_URL } catch { }
        Write-Host "Страница открыта в браузере. Скопируй строку подключения и вставь её ниже." -ForegroundColor Green
        Write-Host "(строка начинается с postgresql:// - вставь целиком, Enter)" -ForegroundColor Green
        Write-Host ""

        $url = ""
        for ($i = 1; $i -le 3; $i++) {
            $entered = Read-Host "Строка подключения"
            if ($entered) { $url = $entered.Trim(); break }
            Write-Host "Пусто. Попробуй ещё раз." -ForegroundColor Yellow
        }
        if (-not $url) {
            Write-Host ""
            Write-Host "Строка подключения не введена - база не настроена." -ForegroundColor Red
            exit 2
        }
        if (-not ($url -match "^postgres(ql)?://")) {
            Write-Host ""
            Write-Host "Это не строка подключения Postgres (нужно начало postgresql://)." -ForegroundColor Red
            exit 2
        }

        # Пулер (PgBouncer) не нужен: у нас мало соединений, а через него
        # ломаются prepared statements. Оставляем только прямой адрес.
        $url = $url -replace "-pooler\.", "."

        # channel_binding - необязательный и капризный параметр, убираем.
        $url = $url -replace "[?&]channel_binding=[^&]*", ""
        $url = $url -replace "\?&", "?"

        # Некоторые строки из консоли Neon не содержат параметр sslmode -
        # без него соединение может уйти без шифрования.
        if ($url -notmatch "sslmode=") {
            $url = $url + $(if ($url -match "\?") { "&" } else { "?" }) + "sslmode=require"
        }

        @(
            "# Neon connection - car-tracker",
            "DATABASE_URL=$url"
        ) | Set-Content -Path $outFile -Encoding UTF8
    }
}

# ---------- 4. Миграции ----------
# Схему создаёт alembic, а не db.create_all(): только так появляется
# таблица alembic_version, и следующие миграции не падают.
Step "Applying migrations"
python (Join-Path $PSScriptRoot "apply_migrations.py")
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Migrations failed - see the output above." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "DONE. Connection saved to: $outFile" -ForegroundColor Green
exit 0

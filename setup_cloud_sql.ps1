# setup_cloud_sql.ps1 - создаёт Google Cloud SQL PostgreSQL для car-tracker.
#
# Запуск в PowerShell из папки проекта:
#   powershell -ExecutionPolicy Bypass -File setup_cloud_sql.ps1
#
# Что делает:
#   1. Проверяет gcloud и биллинг-аккаунт (привязывает проект к счёту, если есть)
#   2. Включает Cloud SQL Admin API
#   3. Создаёт инстанс cars-tracker-db на бесплатном тарифе db-f1-micro
#   4. Создаёт базу cars и пользователя car_tracker
#   5. Открывает доступ извне (Render подключается по публичному IP)
#   6. Сохраняет строку подключения в .cloudsql_connection.txt
#   7. Если есть Render API-ключ - сразу ставит DATABASE_URL и запускает деплой
#
# NOTE: ASCII-only on purpose so PowerShell 5.1 reads it on any code page.

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
    Write-Error "gcloud not found. Install: winget install --id Google.CloudSDK"
    exit 1
}
$script:GcloudExe = $GcloudExe
Write-Host "gcloud: $GcloudExe"

# ---------- 2. Billing account ----------
# Cloud SQL нельзя создать без биллинг-аккаунта. Счёт создаётся только через
# консоль Google (нужен браузер), но привязать проект к уже созданному счёту
# gcloud умеет сам.
Step "Checking billing account"
$accounts = (Invoke-Gcloud -GcloudArgs @("billing","accounts","list","--format=value(name)") -AllowFail).Trim()
# gcloud печатает "Listed 0 items." вместо пустого вывода - это не счёт
$accountLine = @($accounts -split "`n" | Where-Object { $_ -match "^billingAccounts/" } | Select-Object -First 1)
$accounts = if ($accountLine) { $accountLine[0].Trim() } else { "" }
if (-not $accounts) {
    Write-Host ""
    Write-Host "BILLING ACCOUNT NOT FOUND - Cloud SQL cannot be created yet." -ForegroundColor Red
    Write-Host ""
    Write-Host "Do this once (2 minutes, in the browser):" -ForegroundColor Cyan
    Write-Host "  1. Open: $CONSOLE_BILLING_URL"
    Write-Host "  2. Create a billing account (free tier is enough, no charge)."
    Write-Host "  3. Attach project $PROJECT to it."
    Write-Host "  4. Run this script again:"
    Write-Host "     powershell -ExecutionPolicy Bypass -File setup_cloud_sql.ps1"
    Write-Host ""
    exit 2
}
$billingAccount = ($accounts -split "`n")[0].Trim()
Write-Host "Billing account: $billingAccount"

$linked = (Invoke-Gcloud -GcloudArgs @("billing","projects","describe",$PROJECT,"--format=value(billingAccountName)") -AllowFail).Trim()
if ($linked -ne $billingAccount) {
    Step "Linking project $PROJECT to $billingAccount"
    Invoke-Gcloud -GcloudArgs @("billing","projects","link",$PROJECT,"--billing-account=$billingAccount") | Out-Null
} else {
    Write-Host "Project is already linked to $billingAccount"
}

# ---------- 3. API + project ----------
Step "Enabling Cloud SQL Admin API"
Invoke-Gcloud -GcloudArgs @("services", "enable", "sqladmin.googleapis.com", "--project=$PROJECT", "--quiet") | Out-Null
Invoke-Gcloud -GcloudArgs @("config", "set", "project", $PROJECT) | Out-Null

# ---------- 4. Instance ----------
# NOTE: gcloud sql addresses is missing in this SDK build, so the instance
# gets its built-in public IP (--assign-ip). The IP stays the same for the
# whole life of the instance.
# Free tier: shared CPU, 10 GB storage, no automatic backups (they are billed
# separately), no storage auto-increase.
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

# ---------- 5. Wait until the instance is RUNNABLE ----------
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

# ---------- 6. Database and user ----------
Step "Creating database $DB_NAME and user $DB_USER"
Invoke-Gcloud -GcloudArgs @("sql","databases","create",$DB_NAME,"--instance=$INSTANCE","--project=$PROJECT") -AllowFail | Out-Null
# set-password always runs, so a re-run keeps the password in sync with the saved file
Invoke-Gcloud -GcloudArgs @("sql","users","set-password",$DB_USER,"--instance=$INSTANCE","--password=$DB_PASS","--project=$PROJECT") -AllowFail | Out-Null
Invoke-Gcloud -GcloudArgs @("sql","users","create",$DB_USER,"--instance=$INSTANCE","--password=$DB_PASS","--project=$PROJECT") -AllowFail | Out-Null

# ---------- 7. Connection string ----------
Step "Reading public IP"
$ipRaw = Invoke-Gcloud -GcloudArgs @("sql","instances","describe",$INSTANCE,"--project=$PROJECT","--format=value(ipAddresses)")
$m = [regex]::Match($ipRaw, "(\d+\.\d+\.\d+\.\d+)")
if (-not $m.Success) { throw "Could not read instance IP from: $ipRaw" }
$ip = $m.Groups[1].Value

$url = "postgresql://${DB_USER}:${DB_PASS}@${ip}:5432/${DB_NAME}?sslmode=require"
$outFile = Join-Path $PSScriptRoot ".cloudsql_connection.txt"
@(
    "# Google Cloud SQL connection - car-tracker",
    "# Copy the DATABASE_URL line below into Render Dashboard > Environment",
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
Write-Host "DONE. Connection saved to: $outFile" -ForegroundColor Green
Write-Host ""
Write-Host "DATABASE_URL=$url" -ForegroundColor Yellow

# ---------- 8. Render deploy (если есть API-ключ) ----------
$renderKeyFile = Join-Path $PSScriptRoot "render_key.txt"
if (Test-Path $renderKeyFile) {
    Write-Host ""
    Step "Deploying to Render"
    $env:RENDER_API_KEY = ((Get-Content $renderKeyFile -Raw).Trim())
    python (Join-Path $PSScriptRoot "deploy_render.py")
    Remove-Item Env:\RENDER_API_KEY
} else {
    Write-Host ""
    Write-Host "Render: key not found in render_key.txt - skipping deploy." -ForegroundColor Yellow
    Write-Host "Put your Render API key (rnd_...) into render_key.txt and run:"
    Write-Host "  python deploy_render.py"
}
Write-Host ""
Write-Host "DONE." -ForegroundColor Green

# setup_cloud_sql.ps1 - creates Google Cloud SQL PostgreSQL for car-tracker.
#
# Run in PowerShell from the project folder:
#   powershell -ExecutionPolicy Bypass -File setup_cloud_sql.ps1
#
# Steps:
#   1. Enable Cloud SQL Admin API
#   2. Create instance cars-tracker-db (free tier: db-f1-micro)
#   3. Create database cars and user car_tracker
#   4. Allow public access (Render connects from dynamic IPs)
#   5. Save connection string to .cloudsql_connection.txt
#
# NOTE: ASCII-only on purpose so PowerShell 5.1 reads it on any code page.

$ErrorActionPreference = "Continue"

$PROJECT    = "car-tracker-261020"
$INSTANCE   = "cars-tracker-db"
$DB_NAME    = "cars"
$DB_USER    = "car_tracker"
$DB_PASS    = "Ct_" + [guid]::NewGuid().ToString("N").Substring(0,20)
$REGION     = "us-central1"
$TIER       = "db-f1-micro"
$DB_VERSION = "POSTGRES_15"

function Step($msg) { Write-Host ""; Write-Host "=== $msg ===" -ForegroundColor Cyan }

# Run a native command, print its output, fail on non-zero exit code.
function Gcloud {
    param([string[]]$Args, [switch]$AllowFail)
    $out = & $gcloud @Args 2>&1
    $code = $LASTEXITCODE
    $text = ($out | ForEach-Object { "$_" }) -join "`n"
    if ($text) { Write-Host $text }
    if ($code -ne 0 -and -not $AllowFail) {
        throw "gcloud failed (exit $code): $($Args -join ' ')"
    }
    return $text
}

# ---------- 1. Locate gcloud ----------
Step "Checking gcloud"
$gcloud = Get-Command gcloud -ErrorAction SilentlyContinue
if (-not $gcloud) {
    $candidates = @(
        "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
        "$env:LOCALAPPDATA\Google\Cloud SDK\bin\gcloud.cmd",
        "C:\Program Files (x86)\Google\Cloud SDK\bin\gcloud.cmd",
        "C:\Program Files\Google\Cloud SDK\bin\gcloud.cmd"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $gcloud = $c; break }
    }
}
if (-not $gcloud) { Write-Error "gcloud not found. Install: winget install --id Google.CloudSDK" }
Write-Host "gcloud: $gcloud"

# ---------- 2. API + project ----------
Step "Enabling Cloud SQL Admin API"
Gcloud -Args @("services", "enable", "sqladmin.googleapis.com", "--project=$PROJECT", "--quiet") | Out-Null
Gcloud -Args @("config", "set", "project", $PROJECT) | Out-Null

# ---------- 3. Static public IP ----------
Step "Reserving static IP"
$ipName = "$INSTANCE-ip"
$hasIp = Gcloud -Args @("sql", "addresses", "list", "--project=$PROJECT", "--filter=name~$ipName", "--format=value(name)") -AllowFail
if (-not $hasIp) {
    Gcloud -Args @("sql", "addresses", "create", $ipName, "--region=$REGION", "--project=$PROJECT") | Out-Null
}

# ---------- 4. Instance ----------
Step "Creating instance $INSTANCE"
$exists = Gcloud -Args @("sql", "instances", "describe", $INSTANCE, "--project=$PROJECT", "--format=value(name)") -AllowFail
if ($exists -match $INSTANCE) {
    Write-Host "Instance already exists - patching instead."
    Gcloud -Args @("sql", "instances", "patch", $INSTANCE, "--assign-ip", $ipName, "--authorized-networks=0.0.0.0/0", "--project=$PROJECT") | Out-Null
} else {
    Gcloud -Args @("sql", "instances", "create", $INSTANCE,
        "--database-version=$DB_VERSION",
        "--tier=$TIER",
        "--region=$REGION",
        "--availability-type=ZONAL",
        "--assign-ip", $ipName,
        "--project=$PROJECT") | Out-Null
    Gcloud -Args @("sql", "instances", "patch", $INSTANCE, "--authorized-networks=0.0.0.0/0", "--project=$PROJECT") | Out-Null
}

# ---------- 5. Database and user ----------
Step "Creating database $DB_NAME and user $DB_USER"
Gcloud -Args @("sql", "databases", "create", $DB_NAME, "--instance=$INSTANCE", "--project=$PROJECT") -AllowFail | Out-Null
Gcloud -Args @("sql", "users", "create", $DB_USER, "--instance=$INSTANCE", "--password=$DB_PASS", "--project=$PROJECT") -AllowFail | Out-Null

# ---------- 6. Connection string ----------
Step "Reading public IP"
$ipRaw = Gcloud -Args @("sql", "instances", "describe", $INSTANCE, "--project=$PROJECT", "--format=value(ipAddresses)")
$ip = ($ipRaw -split "[;,\r\n]" | Where-Object { $_ -match "^\d+\.\d+\.\d+\.\d+$" } | Select-Object -First 1)
if (-not $ip) { throw "Could not read instance IP from: $ipRaw" }

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
Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  1. Render Dashboard > your service > Environment"
Write-Host "  2. Add DATABASE_URL with the value above"
Write-Host "  3. Save & Deploy"

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

# Run gcloud with given arguments, print its output, fail on non-zero exit code.
# NOTE: parameter is named GcloudArgs (NOT $Args - that name is reserved by PowerShell).
function Invoke-Gcloud {
    param([string[]]$GcloudArgs, [switch]$AllowFail)
    $out = & $script:GcloudExe @GcloudArgs 2>&1
    $code = $LASTEXITCODE
    $text = ($out | ForEach-Object { "$_" }) -join "`n"
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

# ---------- 2. API + project ----------
Step "Enabling Cloud SQL Admin API"
Invoke-Gcloud -GcloudArgs @("services", "enable", "sqladmin.googleapis.com", "--project=$PROJECT", "--quiet") | Out-Null
Invoke-Gcloud -GcloudArgs @("config", "set", "project", $PROJECT) | Out-Null

# ---------- 3. Instance ----------
# NOTE: gcloud sql addresses is missing in this SDK build, so the instance
# gets its built-in public IP (--assign-ip). The IP stays the same for the
# whole life of the instance.
Step "Creating instance $INSTANCE"
$exists = Invoke-Gcloud -GcloudArgs @("sql", "instances", "describe", $INSTANCE, "--project=$PROJECT", "--format=value(name)") -AllowFail
if ($exists -match $INSTANCE) {
    Write-Host "Instance already exists - patching instead."
    Invoke-Gcloud -GcloudArgs @("sql", "instances", "patch", $INSTANCE, "--assign-ip", "--authorized-networks=0.0.0.0/0", "--project=$PROJECT") | Out-Null
} else {
    Invoke-Gcloud -GcloudArgs @("sql", "instances", "create", $INSTANCE,
        "--database-version=$DB_VERSION",
        "--tier=$TIER",
        "--region=$REGION",
        "--availability-type=ZONAL",
        "--assign-ip",
        "--project=$PROJECT") | Out-Null
    Invoke-Gcloud -GcloudArgs @("sql", "instances", "patch", $INSTANCE, "--authorized-networks=0.0.0.0/0", "--project=$PROJECT") | Out-Null
}

# ---------- 4. Wait until the instance is RUNNABLE ----------
Step "Waiting for the instance to become RUNNABLE"
for ($i = 1; $i -le 60; $i++) {
    $state = Invoke-Gcloud -GcloudArgs @("sql", "instances", "describe", $INSTANCE, "--project=$PROJECT", "--format=value(state)") -AllowFail
    $state = $state.Trim()
    Write-Host "  state: $state"
    if ($state -eq "RUNNABLE") { break }
    if ($state -eq "FAILED") { throw "Instance creation failed. Check: gcloud sql operations list --instance=$INSTANCE --project=$PROJECT" }
    Start-Sleep -Seconds 10
}

# ---------- 5. Database and user ----------
Step "Creating database $DB_NAME and user $DB_USER"
Invoke-Gcloud -GcloudArgs @("sql", "databases", "create", $DB_NAME, "--instance=$INSTANCE", "--project=$PROJECT") -AllowFail | Out-Null
# set-password always runs, so a re-run keeps the password in sync with the saved file
Invoke-Gcloud -GcloudArgs @("sql", "users", "set-password", $DB_USER, "--instance=$INSTANCE", "--password=$DB_PASS", "--project=$PROJECT") -AllowFail | Out-Null
Invoke-Gcloud -GcloudArgs @("sql", "users", "create", $DB_USER, "--instance=$INSTANCE", "--password=$DB_PASS", "--project=$PROJECT") -AllowFail | Out-Null

# ---------- 6. Connection string ----------
Step "Reading public IP"
$ipRaw = Invoke-Gcloud -GcloudArgs @("sql", "instances", "describe", $INSTANCE, "--project=$PROJECT", "--format=value(ipAddresses)")
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
Write-Host ""
Write-Host "Next:" -ForegroundColor Cyan
Write-Host "  1. Render Dashboard > your service > Environment"
Write-Host "  2. Add DATABASE_URL with the value above"
Write-Host "  3. Save & Deploy"

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendDir = Join-Path $root "backend"

if (-not $env:DATABASE_URL) {
    $env:DATABASE_URL = "sqlite:///$($root.Path.Replace('\', '/'))/lucky_ticket.db"
}
if (-not $env:EKARTA_FISCAL_BASE_URL) {
    $env:EKARTA_FISCAL_BASE_URL = "https://f.ekarta-ek.ru/fiscal/"
}
if (-not $env:BACKEND_URL) {
    $env:BACKEND_URL = "http://127.0.0.1:8000"
}

Write-Host "Starting backend on http://127.0.0.1:8000"
Start-Process powershell -WindowStyle Hidden -WorkingDirectory $backendDir -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-Command", "python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"
)

if ($env:TG_BOT_TOKEN) {
    Write-Host "Starting Telegram bot polling"
    Start-Process powershell -WindowStyle Hidden -WorkingDirectory $root -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-Command", "python apps/tg-bot/bot.py"
    )
} else {
    Write-Host "TG_BOT_TOKEN is empty; Telegram bot was not started"
}

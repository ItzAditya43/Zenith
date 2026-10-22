# Run the Zenith backend (FastAPI + Uvicorn) on port 8420, Windows.
# Binds to 127.0.0.1 by default. For phone/LAN access set $env:ZENITH_BIND="0.0.0.0"
# AND set a passcode (Settings -> Data) — see MULTIDEVICE.md.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
& .\.venv\Scripts\pip.exe install -q -r requirements.txt
$bind = if ($env:ZENITH_BIND) { $env:ZENITH_BIND } else { "127.0.0.1" }
$port = if ($env:ZENITH_PORT) { $env:ZENITH_PORT } else { "8420" }
Write-Host "Starting Zenith backend on http://${bind}:${port} ..."
& .\.venv\Scripts\uvicorn.exe app.main:app --host $bind --port $port --reload

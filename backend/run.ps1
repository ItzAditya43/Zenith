# Run the Zenith backend (FastAPI + Uvicorn) on port 8420, Windows.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment..."
    python -m venv .venv
}
& .\.venv\Scripts\pip.exe install -q -r requirements.txt
Write-Host "Starting Zenith backend on http://localhost:8420 ..."
& .\.venv\Scripts\uvicorn.exe app.main:app --host 0.0.0.0 --port 8420 --reload

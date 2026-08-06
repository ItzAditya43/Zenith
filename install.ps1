# One-shot local setup for Zenith on Windows: backend venv + deps, frontend deps.
# Does not start any servers — see the printed "Next steps" at the end.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Info($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "!! $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host "ERROR: $msg" -ForegroundColor Red; exit 1 }

# --- Prerequisites -----------------------------------------------------
$pythonBin = $null
foreach ($cand in @("python3.11", "python3.12", "python3.13", "python")) {
    if (Get-Command $cand -ErrorAction SilentlyContinue) {
        $ver = & $cand -c "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"
        if ($ver -in @("3.11", "3.12", "3.13")) { $pythonBin = $cand; break }
    }
}
if (-not $pythonBin) {
    Fail "No Python 3.11-3.13 found on PATH. Install one from https://python.org and re-run (the mcp/starlette/fastapi pins are only verified on 3.11-3.13)."
}
Info "Using $(& $pythonBin --version) ($pythonBin)"

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Fail "node not found. Install Node 18+ from https://nodejs.org and re-run."
}
$nodeMajor = [int]((node -e "console.log(process.versions.node.split('.')[0])"))
if ($nodeMajor -lt 18) { Fail "Node $nodeMajor found, need 18+." }
Info "Using node $(node --version)"

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Warn "ffmpeg not found — video frame/audio extraction won't work until it's on PATH."
}
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    Warn "ollama not found — install it from https://ollama.com and pull a model before chatting."
}

# --- Backend -------------------------------------------------------------
Info "Setting up backend virtualenv + dependencies..."
Set-Location backend
if (-not (Test-Path ".venv")) {
    & $pythonBin -m venv .venv
}
& .\.venv\Scripts\pip.exe install -q --upgrade pip
& .\.venv\Scripts\pip.exe install -q -r requirements.txt
Info "Backend dependencies installed. Verifying the app imports cleanly..."
& .\.venv\Scripts\python.exe -c "import app.main"
if ($LASTEXITCODE -ne 0) { Fail "Backend failed to import — dependency install likely incomplete." }
Set-Location ..

# --- Frontend --------------------------------------------------------------
Info "Setting up frontend dependencies..."
Set-Location frontend
npm install --silent
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }
Set-Location ..

Info "Setup complete."
Write-Host @"

Next steps:
  1. Make sure Ollama is running with at least one model pulled:
       ollama pull llama3.2

  2. Start the backend (terminal 1):
       cd backend
       .\run.ps1

  3. Start the frontend (terminal 2):
       cd frontend
       npm run dev

  Then open http://localhost:5173

  (Prefer Docker instead? `docker compose up -d --build` does all of the
  above in containers — see README.md.)
"@

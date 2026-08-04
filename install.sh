#!/usr/bin/env bash
# One-shot local setup for Zenith: backend venv + deps, frontend deps.
# Does not start any servers — see the printed "Next steps" at the end.
set -euo pipefail
cd "$(dirname "$0")"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$1"; }
warn()  { printf '\033[1;33m!!\033[0m %s\n' "$1"; }
fail()  { printf '\033[1;31mERROR:\033[0m %s\n' "$1"; exit 1; }

# --- Prerequisites -----------------------------------------------------
PYTHON_BIN="$(command -v python3.11 || command -v python3.12 || command -v python3.13 || true)"
if [ -z "$PYTHON_BIN" ]; then
  # Fall back to whatever python3 is, but refuse anything too old/new —
  # the mcp/starlette/fastapi pins are only verified on 3.11-3.13.
  if command -v python3 >/dev/null; then
    ver="$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
    case "$ver" in
      3.11|3.12|3.13) PYTHON_BIN="$(command -v python3)" ;;
      *) fail "Found python3 $ver, but need 3.11-3.13. Install python3.11+ and re-run." ;;
    esac
  else
    fail "python3 not found. Install Python 3.11-3.13 and re-run."
  fi
fi
info "Using $($PYTHON_BIN --version) at $PYTHON_BIN"

command -v node >/dev/null || fail "node not found. Install Node 18+ and re-run."
node_major="$(node -e 'console.log(process.versions.node.split(".")[0])')"
[ "$node_major" -ge 18 ] || fail "Node $node_major found, need 18+."
info "Using node $(node --version)"

command -v ffmpeg >/dev/null || warn "ffmpeg not found — video frame/audio extraction won't work until it's on PATH."
command -v ollama >/dev/null || warn "ollama not found — install it from https://ollama.com and pull a model before chatting."

# --- Backend -------------------------------------------------------------
info "Setting up backend virtualenv + dependencies..."
cd backend
if [ ! -d ".venv" ]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements.txt
info "Backend dependencies installed. Verifying the app imports cleanly..."
python -c "import app.main" || fail "Backend failed to import — dependency install likely incomplete."
deactivate
cd ..

# --- Frontend --------------------------------------------------------------
info "Setting up frontend dependencies..."
cd frontend
npm install --silent
[ -f .env ] || cp .env.example .env
cd ..

info "Setup complete."
cat <<'EOF'

Next steps:
  1. Make sure Ollama is running with at least one model pulled:
       ollama pull llama3.2

  2. Start the backend (terminal 1):
       cd backend && ./run.sh

  3. Start the frontend (terminal 2):
       cd frontend && npm run dev

  Then open http://localhost:5173

  (Prefer Docker instead? `docker compose up -d --build` does all of the
  above in containers — see README.md.)
EOF

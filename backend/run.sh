#!/usr/bin/env bash
# Run the Zenith backend (FastAPI + Uvicorn) on port 8420.
# Binds to 127.0.0.1 by default. For phone/LAN access set ZENITH_BIND=0.0.0.0
# AND set a passcode (Settings -> Data) — remote clients are refused until a
# passcode or shared secret exists. See MULTIDEVICE.md.
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3.11 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
BIND="${ZENITH_BIND:-127.0.0.1}"
PORT="${ZENITH_PORT:-8420}"
echo "Starting Zenith backend on http://${BIND}:${PORT} ..."
uvicorn app.main:app --host "$BIND" --port "$PORT" --reload

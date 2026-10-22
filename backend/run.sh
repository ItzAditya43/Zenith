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
# ./run.sh --profile alice --port 8430  -> a separate Zenith for "alice"
while [ $# -gt 0 ]; do
  case "$1" in
    --profile) export ZENITH_PROFILE="$2"; shift 2 ;;
    --port) export ZENITH_PORT="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
BIND="${ZENITH_BIND:-127.0.0.1}"
PORT="${ZENITH_PORT:-8420}"
echo "Starting Zenith backend${ZENITH_PROFILE:+ (profile: $ZENITH_PROFILE)} on http://${BIND}:${PORT} ..."
uvicorn app.main:app --host "$BIND" --port "$PORT" --reload

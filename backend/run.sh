#!/usr/bin/env bash
# Run the Cortex backend (FastAPI + Uvicorn) on port 8420.
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Creating virtual environment..."
  python3.11 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
echo "Starting Cortex backend on http://localhost:8420 ..."
uvicorn app.main:app --host 0.0.0.0 --port 8420 --reload

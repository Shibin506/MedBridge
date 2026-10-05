#!/usr/bin/env bash
# One command to run MedBridge in demo mode (no API key needed).
#   ./scripts/run-demo.sh
# Then open http://localhost:3000. Press Ctrl+C to stop everything.
set -euo pipefail
cd "$(dirname "$0")/.."

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'. $2"; exit 1; }; }
need python3 "Install Python 3.10+ from https://www.python.org/downloads/"
need node "Install Node.js 20+ from https://nodejs.org"
need npm "Install Node.js 20+ from https://nodejs.org"

busy() { command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }
for port in 8000 3000; do
  if busy "$port"; then echo "Port $port is already in use. Close the program using it and try again."; exit 1; fi
done

echo "==> Setting up the backend (first run takes a minute)"
cd backend
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements-dev.txt
cd ..

echo "==> Setting up the frontend (first run takes a minute)"
(cd frontend && { [ -d node_modules ] || npm install --no-audit --no-fund; })

echo "==> Starting the backend on http://127.0.0.1:8000 (demo mode)"
(cd backend && MEDBRIDGE_DEMO=1 exec .venv/bin/uvicorn app.main:app --port 8000) &
BACKEND_PID=$!
trap 'kill "$BACKEND_PID" 2>/dev/null || true' EXIT INT TERM

echo "==> Starting the website. Open http://localhost:3000 when it says 'Ready'."
cd frontend
npm run dev

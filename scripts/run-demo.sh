#!/usr/bin/env bash
# One command to run MedBridge in demo mode (no API key needed).
#   ./scripts/run-demo.sh
# Then open http://localhost:3000. Press Ctrl+C to stop everything.
set -euo pipefail
cd "$(dirname "$0")/.."

need() { command -v "$1" >/dev/null 2>&1 || { echo "Missing '$1'. $2"; exit 1; }; }

# MedBridge needs Python 3.10+. macOS ships 3.9, which is too old, so look for a newer one.
find_python() {
  for c in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
      echo "$c"; return 0
    fi
  done
  return 1
}
PY=$(find_python) || {
  echo "Python 3.10 or newer is required (your 'python3' is: $(python3 --version 2>&1 || echo missing))."
  echo "Install it with ONE of:"
  echo "  brew install python@3.12        (if you use Homebrew)"
  echo "  or download the installer from https://www.python.org/downloads/"
  echo "Then open a NEW Terminal window and run this script again."
  exit 1
}
echo "==> Using $PY ($($PY --version))"
need node "Install Node.js 20+ from https://nodejs.org"
need npm "Install Node.js 20+ from https://nodejs.org"

busy() { command -v lsof >/dev/null 2>&1 && lsof -iTCP:"$1" -sTCP:LISTEN -t >/dev/null 2>&1; }
for port in 8000 3000; do
  if busy "$port"; then echo "Port $port is already in use. Close the program using it and try again."; exit 1; fi
done

echo "==> Setting up the backend (first run takes a minute)"
cd backend
# A virtual environment made earlier with an old Python is useless: rebuild it.
if [ -d .venv ] && ! .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "==> Removing an old virtual environment"; rm -rf .venv
fi
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
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

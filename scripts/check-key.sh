#!/usr/bin/env bash
# Tests the Gemini key in your .env against Google and tells you what to do. Never prints the key.
set -euo pipefail
cd "$(dirname "$0")/.."
. ./scripts/load-env.sh
load_env .env
[ -x backend/.venv/bin/python ] || { echo "Run ./scripts/run-demo.sh once first (it sets everything up)."; exit 1; }
cd backend && exec .venv/bin/python scripts/check_key.py

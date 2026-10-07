#!/usr/bin/env bash
# Sends one real test text and asks Twilio whether it arrived. Usage: ./scripts/send-test-sms.sh +16692926275
set -euo pipefail
cd "$(dirname "$0")/.."
. ./scripts/load-env.sh
load_env .env
[ -x backend/.venv/bin/python ] || { echo "Run ./scripts/run-demo.sh once first (it sets everything up)."; exit 1; }
cd backend && exec .venv/bin/python scripts/send_test_sms.py "$@"

#!/usr/bin/env bash
# Safest way to save your Gemini key: paste it when asked (nothing shows on screen).
# It writes the .env line for you, then tests the key. Never prints the key.
set -euo pipefail
cd "$(dirname "$0")/.."

printf 'Paste your Gemini API key, then press Enter (nothing will show while you paste): '
IFS= read -rs key || true
echo
key="$(printf '%s' "$key" | tr -d '[:space:]"'"'")"
[ -n "$key" ] || { echo "Nothing was pasted. Run the script again and paste the key with Cmd+V."; exit 1; }

echo "Got a key that starts with “${key:0:4}” and is ${#key} characters long."
case "$key" in
  AIza*|AQ.*) ;;
  *) echo "!! Real keys start with AIza or AQ.  This one does not, so part of it was probably not copied."
     echo "   Use the Copy button next to the key on Google's page (double-clicking stops at the first dot)." ;;
esac

[ -f .env ] || cp .env.example .env
tmp="$(mktemp)"
grep -v '^GEMINI_API_KEY=' .env > "$tmp" || true     # keep every other line
{ printf 'GEMINI_API_KEY=%s\n' "$key"; cat "$tmp"; } > .env
rm -f "$tmp"; chmod 600 .env
echo "Saved to .env"

[ "${MEDBRIDGE_SKIP_CHECK:-}" = 1 ] && exit 0
echo
./scripts/check-key.sh

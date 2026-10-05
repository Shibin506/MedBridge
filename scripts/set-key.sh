#!/usr/bin/env bash
# Safest way to save an AI key: paste it when asked (nothing shows on screen).
# It writes the .env line for you, then tests the key. Never prints the key.
#
#   ./scripts/set-key.sh          Groq (free, key starts with gsk_)   <- default
#   ./scripts/set-key.sh gemini   Google Gemini
set -euo pipefail
cd "$(dirname "$0")/.."

PROVIDER="${1:-groq}"
case "$PROVIDER" in
  groq)   VAR=GROQ_API_KEY;   LABEL="Groq";   WHERE="https://console.groq.com/keys";   GOOD1="gsk_*"; GOOD2="gsk_*"; STARTS="gsk_" ;;
  gemini) VAR=GEMINI_API_KEY; LABEL="Gemini"; WHERE="https://aistudio.google.com/apikey"; GOOD1="AIza*"; GOOD2="AQ.*"; STARTS="AIza or AQ." ;;
  *) echo "Unknown provider '$PROVIDER'. Use: groq or gemini"; exit 1 ;;
esac

printf 'Paste your %s API key, then press Enter (nothing will show while you paste): ' "$LABEL"
IFS= read -rs key || true
echo
key="$(printf '%s' "$key" | tr -d '[:space:]"'"'")"
[ -n "$key" ] || { echo "Nothing was pasted. Run the script again and paste the key with Cmd+V."; exit 1; }

echo "Got a key that starts with “${key:0:4}” and is ${#key} characters long."
# shellcheck disable=SC2254
case "$key" in
  $GOOD1|$GOOD2) ;;
  *) echo "!! A $LABEL key normally starts with $STARTS. This one does not, so part of it was probably not copied."
     echo "   Use the Copy button on $WHERE" ;;
esac

[ -f .env ] || cp .env.example .env
tmp="$(mktemp)"
grep -v "^${VAR}=" .env > "$tmp" || true     # keep every other line
{ printf '%s=%s\n' "$VAR" "$key"; cat "$tmp"; } > .env
rm -f "$tmp"; chmod 600 .env
echo "Saved to .env"

[ "${MEDBRIDGE_SKIP_CHECK:-}" = 1 ] && exit 0
echo
MEDBRIDGE_LLM="$PROVIDER" ./scripts/check-key.sh

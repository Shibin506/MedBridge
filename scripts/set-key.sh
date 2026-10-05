#!/usr/bin/env bash
# Safest way to save an AI key: paste it when asked (nothing shows on screen).
# It writes the .env line for you, then tests the key. Never prints the key.
#
#   ./scripts/set-key.sh          Groq (free, key starts with gsk_)   <- default
#   ./scripts/set-key.sh gemini   Google Gemini
#   ./scripts/set-key.sh twilio   Twilio (text messages): Account SID, Auth Token and your phone number
set -euo pipefail
cd "$(dirname "$0")/.."

PROVIDER="${1:-groq}"

if [ "$PROVIDER" = "twilio" ]; then
  # Twilio needs three values: Account SID, Auth Token, and your Twilio phone number.
  printf 'Paste your Twilio Account SID (starts with AC), then press Enter (hidden): '
  IFS= read -rs sid || true; echo
  printf 'Paste your Twilio Auth Token, then press Enter (hidden): '
  IFS= read -rs token || true; echo
  printf 'Type your Twilio phone number with the + and country code, for example +15551234567: '
  IFS= read -r from || true
  strip() { printf '%s' "$1" | tr -d '[:space:]"'"'"''; }
  sid="$(strip "$sid")"; token="$(strip "$token")"; from="$(strip "$from")"
  [ -n "$sid" ] && [ -n "$token" ] && [ -n "$from" ] || { echo "All three values are needed. Nothing was saved."; exit 1; }
  case "$sid" in AC*) ;; *) echo "!! An Account SID starts with AC. Yours starts with “${sid:0:2}”. Saving anyway; the check below will tell you." ;; esac
  case "$from" in +*) ;; *) echo "!! The phone number should start with + and the country code (for example +1...)." ;; esac
  [ -f .env ] || cp .env.example .env
  tmp="$(mktemp)"
  grep -v -e '^TWILIO_ACCOUNT_SID=' -e '^TWILIO_AUTH_TOKEN=' -e '^TWILIO_FROM_NUMBER=' .env > "$tmp" || true
  { printf 'TWILIO_ACCOUNT_SID=%s\nTWILIO_AUTH_TOKEN=%s\nTWILIO_FROM_NUMBER=%s\n' "$sid" "$token" "$from"; cat "$tmp"; } > .env
  rm -f "$tmp"; chmod 600 .env
  echo "Saved to .env (account “${sid:0:4}…”, token ${#token} characters, number $from)"
  [ "${MEDBRIDGE_SKIP_CHECK:-}" = 1 ] && exit 0
  echo
  exec ./scripts/check-key.sh twilio
fi

case "$PROVIDER" in
  groq)   VAR=GROQ_API_KEY;   LABEL="Groq";   WHERE="https://console.groq.com/keys";   GOOD1="gsk_*"; GOOD2="gsk_*"; STARTS="gsk_" ;;
  gemini) VAR=GEMINI_API_KEY; LABEL="Gemini"; WHERE="https://aistudio.google.com/apikey"; GOOD1="AIza*"; GOOD2="AQ.*"; STARTS="AIza or AQ." ;;
  *) echo "Unknown provider '$PROVIDER'. Use: groq, gemini or twilio"; exit 1 ;;
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

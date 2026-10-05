# Safely load KEY=VALUE lines from a .env file into the environment.
#
# Why not just `source .env`? Because that RUNS the file as shell code: a stray space or a $ in a value
# breaks it, and the error message can print your secret. This reads the file as plain text instead,
# never executes anything, and never prints values.
#
#   source scripts/load-env.sh
#   load_env /path/to/.env
load_env() {
  local file="$1" line key val
  [ -f "$file" ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; esac
    case "$line" in *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    val="${line#*=}"
    key="$(printf '%s' "$key" | tr -d '[:space:]')"
    # API keys and phone numbers never contain spaces, so remove all whitespace and quotes. This also
    # repairs a key that got a line break or space when it was pasted, and Windows (CRLF) line endings.
    val="$(printf '%s' "$val" | tr -d '[:space:]"'"'")"
    case "$key" in [A-Z]*) ;; *) continue ;; esac
    case "$key" in *[!A-Z0-9_]*) continue ;; esac
    [ -n "$val" ] && export "$key=$val"
  done < "$file"
  return 0
}

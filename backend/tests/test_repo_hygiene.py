"""Fails if a real secret is ever committed. Keys belong ONLY in .env (git-ignored)."""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KEY_SHAPES = re.compile(r"AIza[0-9A-Za-z_-]{20,}|AQ\.[A-Za-z0-9_-]{20,}|sk-ant-[A-Za-z0-9_-]{20,}|AC[0-9a-f]{32}\b|SK[0-9a-f]{32}\b|gsk_[A-Za-z0-9]{20,}|\b\d{8,10}:[A-Za-z0-9_-]{35}\b")


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:  # not a git checkout (for example a downloaded zip)
        return [p for p in ROOT.rglob("*") if p.is_file() and ".venv" not in p.parts and "node_modules" not in p.parts]
    return [ROOT / f for f in out.stdout.splitlines()]


def test_env_example_has_no_values():
    """.env.example is a public template: every KEY= line must be empty (or a +1555 style placeholder)."""
    for n, line in enumerate((ROOT / ".env.example").read_text().splitlines(), 1):
        m = re.match(r"^\s*#?\s*([A-Z][A-Z0-9_]*)=(.*)$", line)
        if m and m.group(1) in {"GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "LLM_API_KEY", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TELEGRAM_BOT_TOKEN"}:
            assert m.group(2).strip() == "", f".env.example line {n}: {m.group(1)} must stay empty. Put real keys in .env only."


def test_no_key_shaped_strings_in_tracked_files():
    hits = []
    for path in tracked_files():
        if path.suffix in {".png", ".pdf", ".webp", ".lock", ".svg"} or path.name == "package-lock.json":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if KEY_SHAPES.search(text):
            hits.append(str(path.relative_to(ROOT)))
    assert not hits, f"Possible secret committed in: {hits}. Revoke the key and remove it."


def test_dot_env_is_git_ignored():
    assert re.search(r"^\.env$", (ROOT / ".gitignore").read_text(), re.M)

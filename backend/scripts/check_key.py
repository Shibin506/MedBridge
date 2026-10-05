"""Run through ./scripts/check-key.sh (it loads your .env first)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.keycheck import run  # noqa: E402

sys.exit(run())

"""Run through ./scripts/check-key.sh (it loads your .env first). Add --fix to repair a key that lost its AQ. start."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.keycheck import run  # noqa: E402

sys.exit(run(fix="--fix" in sys.argv[1:]))

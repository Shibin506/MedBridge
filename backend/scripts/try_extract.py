"""Run the real extractor on a sample and print a readable report.

Needs ANTHROPIC_API_KEY in your environment (this calls the real API and costs a little).

    export ANTHROPIC_API_KEY=...        # never commit this
    python scripts/try_extract.py samples/01_heart_failure.txt
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.documents import load_document  # noqa: E402
from app.extractor import Extractor  # noqa: E402


def main(path: str) -> None:
    p = Path(path)
    result = Extractor().extract(load_document(p.name, p.read_bytes()))

    print(f"Diagnosis: {result.diagnosis_summary}\n")
    for title, items in [
        ("MEDICATIONS", result.medications),
        ("FOLLOW-UPS", result.follow_ups),
        ("WARNING SIGNS", result.warning_signs),
        ("RESTRICTIONS", result.restrictions),
    ]:
        print(f"== {title} ({len(items)})")
        for i in items:
            flag = "OK " if not i.needs_confirmation else "!! "
            label = getattr(i, "name", None) or getattr(i, "what", None) or getattr(i, "symptom", None) or i.instruction
            print(f"  {flag}{label}")
            print(f"      quote: {i.source_quote!r}")
            for issue in i.issues:
                print(f"      issue: {issue}")
    if result.unclear_items:
        print("\n== UNCLEAR (a human should check)")
        for u in result.unclear_items:
            print("  -", u)
    print(f"\n{result.items_needing_confirmation} of {result.total_items} items need confirmation.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "samples/01_heart_failure.txt")

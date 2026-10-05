"""Check the two public web services MedBridge uses, against the REAL internet.

    python scripts/check_live_lookups.py

Needs internet access (no API key). Prints PASS / FAIL for each step and what it found, so we can
confirm our code matches the services' real response formats.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.drugs import LookupUnavailable, RxNormResolver  # noqa: E402
from app.safety import HttpJson, OpenFdaLabelSource  # noqa: E402

get = HttpJson(timeout=10)
failed = 0


def check(label, fn):
    global failed
    try:
        ok, detail = fn()
    except LookupUnavailable as exc:
        ok, detail = False, f"could not reach the service ({exc})"
    print(("PASS " if ok else "FAIL ") + label + "\n     " + str(detail))
    failed += 0 if ok else 1


def rxnorm_brand():
    n = RxNormResolver(get).resolve("Cozaar", [])  # not in our built-in table on purpose
    return n.source == "rxnorm" and "losartan" in n.ingredients, f"{n.name} -> {n.ingredients} (source: {n.source})"


def rxnorm_typo():
    n = RxNormResolver(get).resolve("Lisinopryl", [])
    return n.source == "rxnorm" and "lisinopril" in n.ingredients, f"{n.name} -> {n.ingredients} (source: {n.source})"


def fda_label():
    text = OpenFdaLabelSource(get).interactions_text("warfarin")
    return bool(text), (text or "no text returned")[:200].replace("\n", " ") + " ..."


def fda_unknown():
    text = OpenFdaLabelSource(get).interactions_text("notarealdrugxyz")
    return text is None, f"returned {text!r} (expected None)"


check("RxNorm: unknown brand name resolves to its ingredient", rxnorm_brand)
check("RxNorm: misspelled name resolves via closest match", rxnorm_typo)
check("openFDA: warfarin label has an interactions section", fda_label)
check("openFDA: a made-up drug returns 'no label' (not an error)", fda_unknown)
print("\nAll checks passed." if not failed else f"\n{failed} check(s) failed. Paste this output to Claude.")
sys.exit(1 if failed else 0)

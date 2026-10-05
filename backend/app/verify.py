"""Grounding check: do not trust the LLM, check its work with plain code.

For every extracted item we look for its ``source_quote`` inside the original
document text. If the quote is not really there, the model may have invented
or "improved" the item, so we flag it for human confirmation.

This is the main safety idea of Phase 1: *the model proposes, code verifies,
the human confirms.*
"""

import re

from .coverage import uncovered_lines
from .schemas import (
    ExtractionDraft,
    ExtractionResult,
    FollowUp,
    Medication,
    Restriction,
    WarningSign,
)

# Quotes and dashes differ between PDFs and what an LLM types back.
_TRANSLATE = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"})


def normalize(text: str) -> str:
    """Lowercase, unify quote/dash styles, drop hyphenated line breaks, collapse whitespace."""
    text = text.translate(_TRANSLATE).lower()
    text = re.sub(r"-\s*\n\s*", "", text)  # "medi-\ncation" -> "medication"
    return re.sub(r"\s+", " ", text).strip()


_DIGITS = re.compile(r"\d+")
_DECIMALS = re.compile(r"\d+(?:\.\d+)?")
_WORD_COUNTS = {"two": "2", "three": "3", "four": "4", "five": "5", "six": "6"}
_UNITS = r"(?:tablets?|capsules?|pills?|puffs?|drops?|patch(?:es)?|sprays?|spoonfuls?|teaspoons?|tablespoons?)"
_COUNT = re.compile(rf"\b(\d+(?:\.\d+)?|two|three|four|five|six)\s+{_UNITS}\b", re.I)
_UNTIL = re.compile(r"\buntil\b[^.;,]*", re.I)


def _numbers(text: str | None) -> list[str]:
    return _DIGITS.findall(text or "")


def quote_in_source(quote: str, source_norm: str) -> bool:
    q = normalize(quote)
    return len(q) >= 8 and q in source_norm  # tiny quotes prove nothing


def _check(quote: str, source_norm: str) -> tuple[bool, list[str]]:
    if not quote.strip():
        return False, ["No source quote was provided."]
    if not quote_in_source(quote, source_norm):
        return False, ["The supporting quote was not found in the document."]
    return True, []


def verify(draft: ExtractionDraft, source_text: str) -> ExtractionResult:
    src = normalize(source_text)

    meds: list[Medication] = []
    for m in draft.medications:
        grounded, issues = _check(m.source_quote, src)
        # The drug name must really be in the quote that "proves" it.
        if grounded and normalize(m.name) not in normalize(m.source_quote):
            grounded = False
            issues.append("The drug name does not appear in its supporting quote.")
        if m.status != "stop" and (m.dose is None or m.frequency is None):
            issues.append("Dose or frequency is missing; check the paper.")
        # "take 2 tablets": a dose that leaves out the count would look like half the real amount.
        counts = {_WORD_COUNTS.get(c.lower(), c) for c in _COUNT.findall(m.source_quote)} - {"1", "1.0"}
        have = set(_DECIMALS.findall(" ".join(filter(None, [m.dose, m.frequency, m.instructions]))))
        lost = sorted(c for c in counts if c not in have)
        if lost:
            issues.append(f"The paper says to take {', '.join(lost)} at a time (tablets, puffs, ...) but the dose does not "
                          "mention it. Check the dose.")
        # "... until your surgeon says it is safe": a temporary instruction must not look permanent.
        until = _UNTIL.search(m.source_quote)
        if until and "until" not in " ".join(filter(None, [m.duration, m.instructions, m.frequency])).lower():
            issues.append(f"The paper says “{until.group(0).strip()}”, which is missing here. Check whether this is temporary.")
        # Every number in the dose / schedule must be in the quote that "proves" it. This catches an AI that
        # writes 400 mg when the paper says 40 mg, which the quote check alone would not.
        quote_numbers = set(_numbers(m.source_quote))
        for label, value in (("dose", m.dose), ("how often", m.frequency), ("duration", m.duration),
                             ("previous dose", m.previous_dose)):
            missing = [n for n in dict.fromkeys(_numbers(value)) if n not in quote_numbers]
            if missing:
                issues.append(f"The number {', '.join(missing)} in the {label} is not in the supporting quote. "
                              "Check it against your paper.")
        meds.append(Medication(**m.model_dump(), grounded=grounded, needs_confirmation=bool(issues), issues=issues))

    doc_digits = re.sub(r"\D", "", source_text)

    def contact_issue(f) -> list[str]:
        digits = re.sub(r"\D", "", f.contact or "")
        return [] if not digits or digits in doc_digits else ["The phone number was not found in the document. Check it."]

    follow_ups = _wrap(draft.follow_ups, FollowUp, src, contact_issue)
    warnings = _wrap(draft.warning_signs, WarningSign, src)
    restrictions = _wrap(draft.restrictions, Restriction, src)

    all_items = [*meds, *follow_ups, *warnings, *restrictions]
    return ExtractionResult(
        diagnosis_summary=draft.diagnosis_summary,
        medications=meds,
        follow_ups=follow_ups,
        warning_signs=warnings,
        restrictions=restrictions,
        unclear_items=draft.unclear_items,
        total_items=len(all_items),
        items_needing_confirmation=sum(i.needs_confirmation for i in all_items),
        uncovered_lines=uncovered_lines(source_text, draft.model_dump()),
    )


def _wrap(items, model, src: str, extra=None):
    out = []
    for item in items:
        grounded, issues = _check(item.source_quote, src)
        if extra:
            issues = issues + extra(item)
        out.append(model(**item.model_dump(), grounded=grounded, needs_confirmation=bool(issues), issues=issues))
    return out

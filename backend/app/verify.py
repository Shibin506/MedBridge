"""Grounding check: do not trust the LLM, check its work with plain code.

For every extracted item we look for its ``source_quote`` inside the original
document text. If the quote is not really there, the model may have invented
or "improved" the item, so we flag it for human confirmation.

This is the main safety idea of Phase 1: *the model proposes, code verifies,
the human confirms.*
"""

import re

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
        if m.dose is None or m.frequency is None:
            issues.append("Dose or frequency is missing; check the paper.")
        meds.append(Medication(**m.model_dump(), grounded=grounded, needs_confirmation=bool(issues), issues=issues))

    follow_ups = _wrap(draft.follow_ups, FollowUp, src)
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
    )


def _wrap(items, model, src: str):
    out = []
    for item in items:
        grounded, issues = _check(item.source_quote, src)
        out.append(model(**item.model_dump(), grounded=grounded, needs_confirmation=bool(issues), issues=issues))
    return out

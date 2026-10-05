"""Add up a medicine ingredient across everything on the schedule and compare it with a daily limit.

Why: "Tylenol 2 x 500 mg every 6 hours" plus "Percocet 5/325 up to every 6 hours" both contain acetaminophen. Each line looks
fine alone; together they can pass the daily limit. Only code that has the tablet counts, strengths and times can see that.

Only acetaminophen is checked for now (the classic accidental overdose). The limit is the one the PAPER states if it
states one, otherwise the common maximum printed on labels. Anything we cannot add up is reported, never guessed.
"""

import math
import re

from .schedule import build_schedule
from .schemas import DailyTotalFinding, ExtractionResult, Medication, NormalizedMed, TotalContribution

INGREDIENT = "acetaminophen"
LABEL_MAX_MG = 4000
_NUM = r"(\d[\d,]*(?:\.\d+)?)"
_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_COUNT = re.compile(rf"\b(\d+|{'|'.join(_WORDS)})\s+(?:tablets?|capsules?|pills?|caplets?)\b", re.I)
_LIMIT = re.compile(rf"(?:no more than|not more than|maximum of|max(?:imum)?|up to|not (?:to )?exceed|do not (?:take|exceed) more than)\s*{_NUM}\s*mg", re.I)
_EVERY = re.compile(r"every\s+(\d+)(?:\s*(?:-|to)\s*(\d+))?\s*(?:hours?|hrs?)", re.I)


def _num(text: str) -> float:
    return float(text.replace(",", ""))


def _count(dose: str) -> int:
    m = _COUNT.search(dose)
    if not m:
        return 1
    raw = m.group(1).lower()
    return _WORDS.get(raw) or int(raw)


def mg_per_dose(med: Medication, ingredients: list[str]) -> int | None:
    """Milligrams of acetaminophen in ONE dose, or None if the dose cannot be read safely."""
    dose = med.dose or ""
    tablets = _count(dose)
    slash = re.search(rf"{_NUM}\s*/\s*{_NUM}(?:\s*/\s*{_NUM})?\s*mg", dose, re.I)
    if len(ingredients) > 1:  # combination product such as "5/325 mg": strengths follow the ingredient order
        if not slash:
            return None
        strengths = [_num(x) for x in slash.groups() if x]
        if len(strengths) != len(ingredients):
            return None
        return round(strengths[ingredients.index(INGREDIENT)] * tablets)
    mg = re.search(rf"{_NUM}\s*mg", dose, re.I)
    return round(_num(mg.group(1)) * tablets) if mg else None


def paper_limit(ex: ExtractionResult) -> int | None:
    """A daily acetaminophen limit written on the paper itself (in a medicine's instructions or a restriction)."""
    texts = [m.instructions or "" for m in ex.medications if INGREDIENT in (m.name + (m.source_quote or "")).lower() or "tylenol" in m.name.lower()]
    texts += [r.instruction for r in ex.restrictions if INGREDIENT in r.instruction.lower() or "tylenol" in r.instruction.lower()]
    limits = [round(_num(m.group(1))) for t in texts for m in [_LIMIT.search(t)] if m]
    return min(limits) if limits else None


def _as_needed_max(frequency: str | None) -> int | None:
    """Most doses a day an 'as needed' medicine allows: 'every 4-6 hours' -> 24/4 = 6."""
    m = _EVERY.search(frequency or "")
    if m:
        return math.floor(24 / int(m.group(1)))
    text = (frequency or "").lower()
    for word, n in (("four times", 4), ("three times", 3), ("twice", 2)):
        if word in text:
            return n
    return None


def daily_totals(ex: ExtractionResult, normalized: list[NormalizedMed]) -> tuple[list[DailyTotalFinding], list[str]]:
    schedule = build_schedule(ex.medications)
    scheduled_counts: dict[str, int] = {}
    for slot in schedule.slots:
        for item in slot.items:
            scheduled_counts[item.name] = scheduled_counts.get(item.name, 0) + 1
    as_needed = {a.name for a in schedule.as_needed}

    contributions: list[TotalContribution] = []
    notes: list[str] = []
    for med, norm in zip(ex.medications, normalized):
        if med.status == "stop" or INGREDIENT not in norm.ingredients:
            continue
        per_dose = mg_per_dose(med, norm.ingredients)
        if med.name in as_needed:
            doses = _as_needed_max(med.frequency)
        else:
            doses = scheduled_counts.get(med.name)
        if per_dose is None or not doses:
            notes.append(f"We could not add up the acetaminophen in {med.name} (the dose or how often was unclear), "
                         "so it is not in the daily total.")
            continue
        contributions.append(TotalContribution(name=med.name, mg_per_dose=per_dose, doses_per_day=doses,
                                               mg_per_day=per_dose * doses, as_needed=med.name in as_needed))
    if not contributions:
        return [], notes

    total = sum(c.mg_per_day for c in contributions)
    stated = paper_limit(ex)
    limit, source = (stated, "your paper") if stated else (LABEL_MAX_MG, "common label maximum")
    if total <= limit:
        return [], notes
    parts = " + ".join(f"{c.name} {c.mg_per_day:,}" for c in contributions)
    message = (f"If you take everything as written, you could take up to about {total:,} mg of acetaminophen a day "
               f"({parts}). The limit is {limit:,} mg a day ({'what your paper says' if stated else 'the usual maximum on labels'}). "
               "Ask your pharmacist or care team how to use these together before you do.")
    return [DailyTotalFinding(ingredient=INGREDIENT, total_mg=total, limit_mg=limit, limit_source=source,
                              contributors=contributions, message=message)], notes

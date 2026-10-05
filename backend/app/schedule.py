"""Turn "twice daily with meals" into clock times. Plain code, no LLM.

The rule: **never guess**. If a medicine's timing is not one of the patterns below, it goes into
``unscheduled`` with a reason, and the patient is told to follow the paper / ask their care team.
A missing reminder is safer than a wrong one.
"""

import re

from .schemas import (
    AsNeededItem,
    DailySchedule,
    Medication,
    ScheduleItem,
    ScheduleSlot,
    TaperPlan,
    TaperStep,
    UnscheduledItem,
)

# Default clock times. Phase 4 will let the patient change these.
MORNING, MIDDAY, AFTERNOON, EVENING, BEDTIME = "08:00", "12:30", "14:00", "18:30", "21:30"

_AS_NEEDED = re.compile(r"\b(as needed|prn|if needed|when needed|only if|only when|if you (?:have|feel|need|are))\b")
_EVERY_N_HOURS = re.compile(r"\bevery\s+(\d+)(?:\s*(?:-|to)\s*(\d+))?\s*(?:hours?|hrs?)\b")
_FOUR = re.compile(r"\b(four times|4 times|4x|qid)\b")
_THREE = re.compile(r"\b(three times|3 times|3x|tid)\b")
_TWICE = re.compile(r"\b(twice|two times|2 times|2x|bid)\b")
_ONCE = re.compile(r"\b(once|one time|1 time|daily|every day|each day|per day|a day|qd|every morning|every evening|every night|nightly|at bedtime|before bed|in the morning|in the evening|with dinner|with breakfast)\b")
_BEDTIME = re.compile(r"\b(bedtime|before bed|at night|nightly|every night)\b")
_EVENING = re.compile(r"\b(every evening|in the evening|with dinner|at dinner)\b")
_MORNING = re.compile(r"\b(morning|with breakfast)\b")
_MEALS = re.compile(r"\b(with meals|with each meal|with food|before meals|after meals)\b")
_WEEKLY = re.compile(r"\b(weekly|once a week|every week|every other day|every\s+\d+\s+days?|every\s+\d+\s+weeks?)\b")
_TAPER_STEP = re.compile(
    r"(\d+(?:\.\d+)?)\s*(mg|mcg|g|ml|units?)\s*(?:once\s+|twice\s+)?(?:daily|a day|per day|each day)?\s*for\s*(\d+)\s*days?"
)

# "every N hours" -> clock times (overnight doses are literal; the paper said every 6 hours)
_INTERVAL_TIMES = {24: ["08:00"], 12: ["08:00", "20:00"], 8: ["06:00", "14:00", "22:00"], 6: ["06:00", "12:00", "18:00", "00:00"]}


def label_for(hhmm: str) -> str:
    hour = int(hhmm[:2])
    if hour < 5:
        return "Overnight"
    if hour < 10:
        return "Morning"
    if hour < 13:
        return "Midday"
    if hour < 17:
        return "Afternoon"
    if hour < 20:
        return "Evening"
    return "Bedtime"


def _note(m: Medication, extra: str | None = None) -> str | None:
    duration = (m.duration if re.match(r"(?i)\s*(until|after|then)\b", m.duration or "") else f"for {m.duration}") if m.duration else None
    parts = [m.instructions, duration, extra,
             "dose changed" if m.status == "changed" else None]
    text = "; ".join(p for p in parts if p)
    return text or None


def _taper(m: Medication) -> TaperPlan | None:
    # Look in ONE place at a time. Joining the fields would find the same steps twice
    # (once in the dose, once in the quote) and invent extra days.
    sources = [" ".join(filter(None, [m.dose, m.frequency, m.duration, m.instructions])), m.source_quote]
    for text in (t.lower() for t in sources):
        found = _TAPER_STEP.findall(text)
        if len(found) >= 2 and len({(d, u) for d, u, _ in found}) >= 2:
            break
    else:
        return None
    everything = " ".join(filter(None, [m.dose, m.frequency, m.duration, m.instructions, m.source_quote])).lower()
    steps, day = [], 1
    for dose, unit, days in found:
        n = int(days)
        steps.append(TaperStep(when=f"Day {day}" if n == 1 else f"Days {day}-{day + n - 1}", dose=f"{dose} {unit}"))
        day += n
    return TaperPlan(
        name=m.name, steps=steps, after="Then stop." if "then stop" in everything else None,
        note="; ".join(p for p in [m.instructions] if p) or None,
    )


def _times_for(freq: str, combined: str) -> tuple[list[str], str | None] | str:
    """Return (times, extra_note) or a string explaining why we will not guess."""
    meals = bool(_MEALS.search(combined))
    meal_note = "with meals" if meals else None
    if (m := _EVERY_N_HOURS.search(freq)):
        if m.group(2):  # "every 4-6 hours" without "as needed"
            return f"The paper gives a range ({m.group(0)}), so we cannot pick exact times."
        hours = int(m.group(1))
        if hours in _INTERVAL_TIMES:
            return _INTERVAL_TIMES[hours], meal_note
        return f"Every {hours} hours is not a schedule we set automatically."
    if _FOUR.search(freq):
        return ["08:00", "12:00", "16:00", "20:00"], meal_note
    if _THREE.search(freq):
        return ([MORNING, MIDDAY, EVENING] if meals else [MORNING, AFTERNOON, "20:00"]), meal_note
    if _TWICE.search(freq):
        return ([MORNING, EVENING] if meals else [MORNING, "20:00"]), meal_note
    if _ONCE.search(freq) or _BEDTIME.search(freq):
        if _BEDTIME.search(combined):
            return [BEDTIME], meal_note
        if _EVENING.search(combined):
            return [EVENING], meal_note
        return [MORNING], meal_note
    return f"We could not understand “{freq}”."


def build_schedule(medications: list[Medication]) -> DailySchedule:
    slots: dict[str, list[ScheduleItem]] = {}
    as_needed: list[AsNeededItem] = []
    tapers: list[TaperPlan] = []
    unscheduled: list[UnscheduledItem] = []

    for m in medications:
        if m.status == "stop":
            continue
        if taper := _taper(m):
            tapers.append(taper)
            continue
        freq = (m.frequency or "").lower().strip()
        if not freq:
            unscheduled.append(UnscheduledItem(name=m.name, reason="Your paper does not say how often to take this."))
            continue
        combined = f"{freq} {(m.instructions or '').lower()}"
        if _AS_NEEDED.search(combined):
            as_needed.append(AsNeededItem(name=m.name, dose=m.dose, how_often=m.frequency, note=_note(m)))
            continue
        if _WEEKLY.search(freq):
            unscheduled.append(UnscheduledItem(name=m.name, reason=f"“{m.frequency}” needs specific days; follow your paper."))
            continue
        result = _times_for(freq, combined)
        if isinstance(result, str):
            unscheduled.append(UnscheduledItem(name=m.name, reason=result))
            continue
        times, extra = result
        for t in times:
            slots.setdefault(t, []).append(ScheduleItem(name=m.name, dose=m.dose, note=_note(m, extra), status=m.status))

    return DailySchedule(
        slots=[ScheduleSlot(time=t, label=label_for(t), items=items) for t, items in sorted(slots.items())],
        as_needed=as_needed, tapers=tapers, unscheduled=unscheduled,
    )

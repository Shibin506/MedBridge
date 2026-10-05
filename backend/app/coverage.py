"""Which sentences of the paper did NOTHING we extracted cover?

The AI sometimes drops a line ("You may shower after 48 hours", "for pain you may use acetaminophen, max 3,000 mg").
It cannot tell us what it forgot, but code can: compare every sentence of the paper with the words in everything
that was extracted. Sentences that are mostly not covered are shown to the patient as "lines we did not use", so a
dropped instruction is visible instead of silently missing.

This is a hint, not a guarantee. It can show harmless lines (reasons, side effects) and it can miss a dropped line whose
words happen to appear elsewhere.
"""

import re

MAX_LINES = 12
COVERED_ENOUGH = 0.75  # share of a sentence's meaningful words that must appear in the extracted items
MIN_WORDS = 2  # short sentences matter too ("You may shower after 48 hours.")

_STOP = set("""a an the to of and or is are was were be been it its this that these those you your yours i we our they them
their he she his her in on at for with by from as if so than then too very can could may might will would should do does
did not no yes any all some more most other such only also just up out about into over after before between each
there here what which who whom when where why how have has had having take taking taken""".split())

_META = re.compile(r"^(patient|name|age|dob|mrn|ref|encounter|admit(ted)?|discharge(d)?( date)?|surgery date|going home|"
                   r"attending|surgeon|discharging physician|physician|ref)\b", re.I)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _meaningful(text: str) -> list[str]:
    return [w for w in _words(text) if (w not in _STOP and not w.isdigit()) or (w.isdigit() and len(w) >= 2)]


def _is_boilerplate(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    if not letters:
        return True
    if "SYNTHETIC DOCUMENT" in line or _META.match(line):
        return True
    upper = sum(c.isupper() for c in letters) / len(letters)
    first_words = line.split()[:3]
    shouting = len(first_words) == 3 and all(w.strip(",.-:").isupper() for w in first_words)  # "LAKESIDE MEDICAL CENTER - ..."
    return (upper > 0.7 and len(line) < 80) or shouting  # section headings such as "FOLLOW-UP"


_ABBREVIATIONS = ("Dr.", "Mr.", "Mrs.", "Ms.", "St.", "vs.", "e.g.", "i.e.")


def sentences(document: str) -> list[str]:
    """Join wrapped lines, then split into sentences (without cutting at "Dr.")."""
    blocks: list[str] = []
    for raw in document.splitlines():
        line = raw.rstrip()
        if not line.strip():
            blocks.append("")
            continue
        is_bullet = bool(re.match(r"^\s*(?:[-*•]|\d+[.)])\s+", line))                  # a bullet always starts a new item
        text = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).strip()
        previous = blocks[-1] if blocks else ""
        indented = raw[:1].isspace() and bool(previous) and not is_bullet       # "   water pill..." continues the line above
        wrapped = bool(previous) and not is_bullet and previous[-1] not in ".!?:;" and (text[:1].islower() or text[:1].isdigit())  # "...caused by\ncongestive heart..."
        if indented or wrapped:
            blocks[-1] += " " + text
        else:
            blocks.append(text)
    out: list[str] = []
    for block in blocks:
        parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", block)
        merged: list[str] = []
        for part in parts:
            if merged and merged[-1].endswith(_ABBREVIATIONS):
                merged[-1] += " " + part
            else:
                merged.append(part)
        out.extend(p.strip() for p in merged if p.strip())
    return out


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _strings(v)]
    return []


def uncovered_lines(document: str, extracted: dict) -> list[str]:
    """``extracted`` is the draft/result as a dict; every string in it counts as coverage."""
    covered = set(_meaningful(" ".join(_strings(extracted))))
    out: list[str] = []
    for sentence in sentences(document):
        if len(sentence) < 20 or _is_boilerplate(sentence):
            continue
        if sentence[-1] not in ".!?" and len(sentence.split()) <= 4:
            continue  # short heading such as "Follow-up appointments"
        words = _meaningful(sentence)
        if len(words) < MIN_WORDS:
            continue
        if sum(w in covered for w in words) / len(words) < COVERED_ENOUGH:
            out.append(sentence)
    return out[:MAX_LINES]

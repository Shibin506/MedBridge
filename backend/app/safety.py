"""Safety checks that run on the patient's CONFIRMED medicine list. Plain code, no LLM.

1. duplicates          two active medicines share an ingredient (Tylenol + Percocet = acetaminophen twice)
2. stopped conflicts   the paper says STOP X, but another listed medicine contains X
3. interaction hints   an FDA drug label for one medicine explicitly names another one on the list

The third check is deliberately modest. It only finds interactions that a label names explicitly
and it quotes the label's own sentence. "No hint found" never means "no interaction"; the UI says so.
"""

import re
from typing import Protocol

import httpx

from .drugs import LocalResolver, LookupUnavailable, Resolver, RxNormResolver, aliases_from, names_for
from .schemas import (
    DuplicateFinding,
    ExtractionResult,
    InteractionHint,
    NormalizedMed,
    SafetyReport,
    StoppedConflict,
)

MAX_LABEL_LOOKUPS = 12
EXCERPT_CHARS = 320
ALWAYS_NOTE = (
    "This check only finds problems that are named explicitly in the information we looked at. "
    "Not finding a warning does not mean a combination is safe. Ask your pharmacist to review your full list, "
    "including anything you buy without a prescription."
)


# --------------------------------------------------------------------------
# Where label text comes from
# --------------------------------------------------------------------------
class LabelSource(Protocol):
    source_name: str

    def interactions_text(self, ingredient: str) -> str | None:
        """Text of the 'drug interactions' section, None if no label found. Raises LookupUnavailable."""


class HttpJson:
    """Tiny JSON-over-HTTP helper with short timeouts. 404 -> None, other failures -> LookupUnavailable."""

    def __init__(self, timeout: float = 5.0):
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "MedBridge/0.3"})

    def __call__(self, url: str, params: dict) -> dict | None:
        try:
            r = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            raise LookupUnavailable(str(exc)) from exc
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise LookupUnavailable(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as exc:
            raise LookupUnavailable("bad JSON") from exc


class OpenFdaLabelSource:
    source_name = "FDA drug label"
    URL = "https://api.fda.gov/drug/label.json"

    def __init__(self, get_json):
        self._get = get_json
        self._cache: dict[str, str | None] = {}

    def interactions_text(self, ingredient: str) -> str | None:
        if ingredient not in self._cache:
            data = self._get(self.URL, {"search": f'openfda.generic_name:"{ingredient}"', "limit": 1})
            results = (data or {}).get("results") or []
            sections = results[0].get("drug_interactions") if results else None
            self._cache[ingredient] = " ".join(sections) if sections else None
        return self._cache[ingredient]


# --------------------------------------------------------------------------
# The checker
# --------------------------------------------------------------------------
def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text)) if s.strip()]


def _mention(text: str, terms: list[str]) -> str | None:
    """First sentence of ``text`` that names any of ``terms`` as a whole word."""
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms if len(t) >= 4) + r")\b", re.I) if any(len(t) >= 4 for t in terms) else None
    if not pattern:
        return None
    for sentence in _sentences(text):
        if pattern.search(sentence):
            return sentence if len(sentence) <= EXCERPT_CHARS else sentence[: EXCERPT_CHARS - 1].rstrip() + "…"
    return None


class SafetyChecker:
    def __init__(self, resolver: Resolver | None = None, labels: LabelSource | None = None):
        self.resolver = resolver or LocalResolver()
        self.labels = labels

    def check(self, ex: ExtractionResult) -> SafetyReport:
        normalized: list[NormalizedMed] = []
        for m in ex.medications:
            normalized.append(self.resolver.resolve(m.name, aliases_from(m.name, m.source_quote)))

        active = [(m, n) for m, n in zip(ex.medications, normalized) if m.status != "stop"]
        stopped = [(m, n) for m, n in zip(ex.medications, normalized) if m.status == "stop"]

        # 1. duplicates among active medicines
        by_ing: dict[str, list[str]] = {}
        for m, n in active:
            for ing in n.ingredients:
                if m.name not in by_ing.setdefault(ing, []):
                    by_ing[ing].append(m.name)
        duplicates = [
            DuplicateFinding(
                ingredient=ing, medicines=names,
                message=f"{' and '.join(names)} both contain {ing}. Taking them together can add up to more "
                        f"{ing} than is safe. Ask your pharmacist or care team how to take them before using both.",
            )
            for ing, names in by_ing.items() if len(names) > 1
        ]

        # 2. the paper says stop X, but something still listed contains X
        conflicts: list[StoppedConflict] = []
        for sm, sn in stopped:
            for ing in sn.ingredients:
                for name in by_ing.get(ing, []):
                    conflicts.append(StoppedConflict(
                        ingredient=ing, stopped=sm.name, still_listed=name,
                        message=f"Your paper says to stop {sm.name}, but {name} also contains {ing}. "
                                f"Ask your care team which instruction is right before you take {name}.",
                    ))

        # 3. interaction hints from label text
        interactions, status, notes = self._interactions(list(by_ing))
        notes.append(ALWAYS_NOTE)
        if any(n.source == "name" for n in normalized):
            notes.append("Some medicine names were taken as written and could not be matched to a drug database: "
                         + ", ".join(n.name for n in normalized if n.source == "name") + ".")
        return SafetyReport(normalized=normalized, duplicates=duplicates, stopped_conflicts=conflicts,
                            interactions=interactions, interaction_check=status, notes=notes)

    def _interactions(self, ingredients: list[str]):
        if self.labels is None:
            return [], "not_run", ["Interaction lookup is not set up in this version."]
        if len(ingredients) < 2:
            return [], "done", []
        texts: dict[str, str | None] = {}
        try:
            for ing in ingredients[:MAX_LABEL_LOOKUPS]:
                texts[ing] = self.labels.interactions_text(ing)
        except LookupUnavailable:
            return [], "unavailable", ["We could not reach the drug-information service, so interactions were NOT checked. "
                                       "Ask your pharmacist."]
        hints: list[InteractionHint] = []
        seen: set[frozenset[str]] = set()
        for a in texts:
            for b in texts:
                if a == b or not texts[a] or frozenset((a, b)) in seen:
                    continue
                sentence = _mention(texts[a], names_for(b))
                if sentence:
                    seen.add(frozenset((a, b)))
                    hints.append(InteractionHint(drug_a=a, drug_b=b, source=f"{self.labels.source_name} for {a}", excerpt=sentence))
        notes = []
        if len(ingredients) > MAX_LABEL_LOOKUPS:
            notes.append(f"Only the first {MAX_LABEL_LOOKUPS} ingredients were checked for interactions.")
        return hints, "done", notes


def build_live_checker() -> SafetyChecker:
    """The real thing: NIH RxNorm names + FDA label text over the internet (short timeouts)."""
    get = HttpJson()
    return SafetyChecker(resolver=RxNormResolver(get), labels=OpenFdaLabelSource(get))

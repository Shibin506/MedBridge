"""Work out WHICH active ingredients a medicine contains, so we can spot duplicates.

"Tylenol" and "acetaminophen" are the same drug; "Percocet" contains acetaminophen too. Taking
both can add up to an unsafe amount, a classic cause of accidental overdose.

Resolution order (first hit wins):
  1. a small built-in brand->ingredient table (works offline, instant)
  2. NIH RxNorm lookup (optional; used only for names the table does not know)
  3. otherwise we ASSUME the written name is the generic name and say so (source="name")
"""

import re
from typing import Protocol

from .schemas import NormalizedMed

BRANDS: dict[str, list[str]] = {
    "tylenol": ["acetaminophen"], "percocet": ["oxycodone", "acetaminophen"], "norco": ["hydrocodone", "acetaminophen"],
    "vicodin": ["hydrocodone", "acetaminophen"], "oxycontin": ["oxycodone"], "roxicodone": ["oxycodone"],
    "advil": ["ibuprofen"], "motrin": ["ibuprofen"], "motrin ib": ["ibuprofen"], "aleve": ["naproxen"], "naprosyn": ["naproxen"],
    "bayer": ["aspirin"], "ecotrin": ["aspirin"], "lasix": ["furosemide"], "toprol": ["metoprolol"], "toprol-xl": ["metoprolol"],
    "lopressor": ["metoprolol"], "zestril": ["lisinopril"], "prinivil": ["lisinopril"], "lipitor": ["atorvastatin"],
    "zocor": ["simvastatin"], "crestor": ["rosuvastatin"], "glucophage": ["metformin"], "augmentin": ["amoxicillin", "clavulanate"],
    "eliquis": ["apixaban"], "xarelto": ["rivaroxaban"], "coumadin": ["warfarin"], "jantoven": ["warfarin"],
    "plavix": ["clopidogrel"], "mucinex": ["guaifenesin"], "proair": ["albuterol"], "ventolin": ["albuterol"],
    "colace": ["docusate"], "senokot": ["senna"], "zofran": ["ondansetron"], "synthroid": ["levothyroxine"],
    "norvasc": ["amlodipine"], "prilosec": ["omeprazole"], "nexium": ["esomeprazole"], "benadryl": ["diphenhydramine"],
    "celebrex": ["celecoxib"], "deltasone": ["prednisone"],
}

# Words that describe the salt or release form, not the drug ("metoprolol succinate ER").
_TRAILING = {
    "succinate", "tartrate", "hydrochloride", "hcl", "sulfate", "maleate", "besylate", "mesylate", "phosphate",
    "citrate", "acetate", "bromide", "sodium", "er", "xr", "sr", "cr", "dr", "xl", "la", "cd", "odt", "ec",
}
_NOISE = {"tablet", "tablets", "tab", "tabs", "capsule", "capsules", "cap", "caps", "pill", "pills", "inhaler", "mg", "mcg", "ml", "g"}


def _clean(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text.lower())  # drop "(Lasix)"
    text = re.sub(r"[\d.,]+\s*(?:mg|mcg|g|ml|units?|meq)?\b", " ", text)  # drop strengths
    return re.sub(r"\s+", " ", text).strip(" -:,;")


def _strip_salt(tokens: list[str]) -> list[str]:
    tokens = [t for t in tokens if t not in _NOISE]
    while len(tokens) > 1 and tokens[-1] in _TRAILING:
        tokens.pop()
    return tokens


def aliases_from(name: str, source_quote: str) -> list[str]:
    """Names in brackets next to the drug: 'Tylenol (acetaminophen)' -> ['acetaminophen']."""
    found: list[str] = []
    for text in (name, source_quote):
        for group in re.findall(r"\(([^)]*)\)", text):
            for part in re.split(r"[,/]| or ", group):
                part = part.strip()
                if part and not re.search(r"\d", part):
                    found.append(part)
    return found


def split_ingredients(cleaned: str) -> list[str]:
    parts = re.split(r"\s*(?:/|\+|-|,|&|\band\b|\bwith\b)\s*", cleaned)
    out = []
    for part in parts:
        tokens = _strip_salt(part.split())
        if tokens:
            out.append(" ".join(tokens))
    return out


def names_for(ingredient: str) -> list[str]:
    """The ingredient plus single-ingredient brand names, for matching text like 'Coumadin'."""
    return [ingredient, *(b for b, ing in BRANDS.items() if ing == [ingredient])]


class Resolver(Protocol):
    def resolve(self, name: str, aliases: list[str]) -> NormalizedMed: ...


class LocalResolver:
    """Offline resolver: brand table, then 'assume the written name is generic'."""

    def resolve(self, name: str, aliases: list[str]) -> NormalizedMed:
        found = self._from_table(name, aliases)
        if found:
            return NormalizedMed(name=name, ingredients=found, source="local")
        return NormalizedMed(name=name, ingredients=split_ingredients(_clean(name)) or [name.lower()], source="name")

    @staticmethod
    def _from_table(name: str, aliases: list[str]) -> list[str]:
        ingredients: list[str] = []
        for candidate in (name, *aliases):
            key = _clean(candidate)
            first = " ".join(_strip_salt(key.split()))
            for k in (key, first, first.split(" ")[0] if first else ""):
                if k in BRANDS:
                    ingredients += [i for i in BRANDS[k] if i not in ingredients]
                    break
        return ingredients


class LookupUnavailable(RuntimeError):
    """A web lookup failed (offline, timeout, rate limit). Never treated as 'no problem'."""


class RxNormResolver:
    """Adds an NIH RxNorm lookup for names the local table does not know.

    ``get_json(url, params) -> dict | None`` is injected (real: HttpJson; tests: a fake).
    After the first network failure we stop calling the service for this request (circuit breaker).
    """

    BASE = "https://rxnav.nlm.nih.gov/REST"

    def __init__(self, get_json, local: LocalResolver | None = None):
        self._get = get_json
        self._local = local or LocalResolver()
        self._cache: dict[str, list[str] | None] = {}
        self.unavailable = False  # the service could not be reached
        self.unmatched: list[str] = []  # the service answered but did not know the name

    def resolve(self, name: str, aliases: list[str]) -> NormalizedMed:
        local = self._local.resolve(name, aliases)
        if local.source == "local" or self.unavailable:
            return local
        term = " ".join(_strip_salt(_clean(name).split())) or name
        if term not in self._cache:
            try:
                self._cache[term] = self._lookup(term)
            except LookupUnavailable:
                self.unavailable = True
                return local
        ingredients = self._cache[term]
        if not ingredients:
            if name not in self.unmatched:
                self.unmatched.append(name)
            return local
        return NormalizedMed(name=name, ingredients=ingredients, source="rxnorm")

    def _lookup(self, term: str) -> list[str] | None:
        data = self._get(f"{self.BASE}/rxcui.json", {"name": term, "search": 2}) or {}
        ids = (data.get("idGroup") or {}).get("rxnormId") or []
        if not ids:  # misspelled or unusual name: ask for the closest match
            data = self._get(f"{self.BASE}/approximateTerm.json", {"term": term, "maxEntries": 1}) or {}
            cands = (data.get("approximateGroup") or {}).get("candidate") or []
            ids = [cands[0]["rxcui"]] if cands and "rxcui" in cands[0] else []
        if not ids:
            return None
        rel = self._get(f"{self.BASE}/rxcui/{ids[0]}/related.json", {"tty": "IN"}) or {}
        names: list[str] = []
        for group in (rel.get("relatedGroup") or {}).get("conceptGroup") or []:
            for prop in group.get("conceptProperties") or []:
                n = str(prop.get("name", "")).lower().strip()
                if n and n not in names:
                    names.append(n)
        return names or None

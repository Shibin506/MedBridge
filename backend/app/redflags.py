"""Red-flag rules for text replies. Plain code, no AI.

Where the rules come from:
  1. the patient's OWN confirmed warning signs (their paper says "Call 911" or "Call your doctor" for each), matched to a
     small list of symptom "concepts" so that "my ankles are swollen" matches "more swelling in your feet, ankles or belly";
  2. a short built-in list of universal emergencies (chest pain, fainting, stroke signs, vomiting blood, suicidal
     thoughts, a closing throat) that always means "call 911".

Safety choices:
  * negation is understood ("no chest pain" does not alarm);
  * a message that sounds worrying but matches nothing is NOT answered with reassurance: it becomes a "review" alert;
  * when a paper's 911 sign needs severity ("severe trouble breathing") and the message does not sound severe, the
    reply is downgraded to "call your doctor today", with a line saying when to call 911 instead.
"""

import re
from dataclasses import dataclass

from .schemas import ExtractionResult

URGENT, SAME_DAY, REVIEW = "urgent", "same_day", "review"


@dataclass(frozen=True)
class Concept:
    id: str
    label: str            # short, used in questions: "swelling"
    message: re.Pattern   # what a patient might write
    paper: re.Pattern     # how a discharge paper might word it


def _c(id_: str, label: str, message: str, paper: str | None = None) -> Concept:
    return Concept(id_, label, re.compile(message, re.I), re.compile(paper or message, re.I))


CONCEPTS: list[Concept] = [
    _c("chest_pain", "chest pain", r"chest (pain|pressure|tightness|hurts?|is hurting|feels? (tight|heavy))|(pain|pressure|tightness|squeezing|heaviness) (in|on) (my |the )?chest|"
       r"heart attack|elephant on my chest"),
    _c("breathing", "trouble breathing",
       r"short(ness)? of breath|can'?t breathe|cannot breathe|trouble breathing|hard to breathe|difficulty breathing|"
       r"out of breath|gasping|struggling to breathe|breathless|wheez",
       r"short(ness)? of breath|trouble breathing|difficulty breathing|breathing|breathless"),
    _c("fainting", "fainting", r"faint(ed|ing)?\b|passed out|blacked out|black(ed)? out|unconscious|collapsed|unresponsive", r"faint|unconscious|passing out"),
    _c("stroke", "stroke signs",
       r"face (is )?(drooping|droopy)|slurred speech|can'?t (move|lift) (my )?(arm|leg)|weak(ness)? on (one|my) side|"
       r"sudden (numbness|confusion|trouble speaking)", r"stroke|face droop|slurred"),
    _c("blood_up", "coughing or vomiting blood", r"(vomit(ing|ed)?|throwing up|coughing( up)?|cough(ed)? up) (some )?blood|blood in (my )?(vomit|cough)",
       r"(vomit|cough)\w* (up )?blood|blood in (the )?(vomit|cough)|blood"),
    _c("foamy", "pink foamy mucus", r"pink,? foamy", r"pink,? foamy"),
    _c("bleeding", "bleeding", r"bleed(ing|s)|blood (is )?(soaking|pouring)", r"bleed"),
    _c("anaphylaxis", "throat swelling", r"throat (is )?(closing|swelling)|can'?t swallow|(tongue|lips|face) (is |are )?(swelling|swollen)",
       r"throat|tongue|lips|allergic reaction"),
    _c("suicidal", "thoughts of self-harm", r"kill myself|end my life|suicid|want to die|better off dead|hurt myself", r"suicid|self-harm|harm yourself"),
    _c("swelling", "swelling", r"swell(ing|s)?\b|swollen|puffy|bloated", r"swell|puffy|bloated"),
    _c("dizziness", "dizziness", r"dizz(y|iness)|light-?headed|room (is )?spinning|woozy", r"dizz|light-?headed"),
    _c("fast_heartbeat", "a fast heartbeat", r"(fast|racing|pounding|rapid|irregular) (heart ?beat|heart|pulse)|heart (is )?racing|palpitations",
       r"heart ?beat|palpitation|racing heart"),
    _c("orthopnea", "needing more pillows", r"more pillows|can'?t lie (flat|down)|wak(e|ing) up (short of breath|gasping)", r"pillows|lie flat"),
    _c("fever", "fever", r"fever|chills|feel(ing)? feverish", r"fever|temperature|chills"),
    _c("vomiting", "vomiting", r"vomit|throwing up|can'?t keep (anything|food|pills|medicine|my medicine) down", r"vomit|nausea that"),
    _c("diarrhea", "diarrhea", r"diarrh?ea|loose stools?", r"diarrh?ea"),
    _c("rash", "a rash", r"rash|hives|itch(y|ing) all over", r"rash|hives"),
    _c("wound", "redness or drainage at the wound", r"(redness|pus|drainage|draining|oozing|leak(s|ing|ed)?|red and warm|warm and red)|wound (is )?(red|open|leaking)|incision (is )?(red|open|leaking|hot)",
       r"redness|drainage|incision|wound|pus"),
    _c("calf", "calf pain or swelling", r"calf (pain|swelling|swollen|tender|hurts)|leg (is )?(swollen|painful) and (red|warm)", r"calf"),
    _c("yellow", "yellow skin or eyes", r"yellow(ing)? (skin|eyes)|jaundice", r"yellow|jaundice"),
    _c("belly_pain", "belly pain", r"(belly|stomach|abdominal|abdomen) (pain|cramps?|hurts?)|pain in (my )?(belly|stomach|abdomen)", r"(belly|abdominal|stomach) pain"),
    _c("confusion", "confusion", r"confus(ed|ion)|don'?t know where i am|not making sense", r"confus"),
    _c("blue", "blue lips or fingertips", r"(blue|gray|grey) (lips|fingertips|fingers)|lips (are |look )?blue", r"blue|bluish"),
]
BY_ID = {c.id: c for c in CONCEPTS}

# Always an emergency, with or without a paper.
UNIVERSAL_URGENT = {"chest_pain", "fainting", "stroke", "blood_up", "anaphylaxis", "suicidal", "foamy", "blue"}
# Only an emergency when the message also sounds severe.
SEVERE_ONLY = {"breathing", "bleeding", "belly_pain"}
_SEVERE = re.compile(r"severe|very bad|really bad|terrible|worst|unbearable|can'?t breathe|cannot breathe|gasping|won'?t stop|will not stop|"
                     r"soaking|pouring|a lot|heavily|struggling|can'?t catch my breath|constant", re.I)
_NEGATORS = {"no", "not", "without", "never", "denies", "deny", "none", "nothing", "dont", "don't", "didnt", "didn't", "havent",
             "haven't", "hasnt", "hasn't", "isnt", "isn't", "arent", "aren't", "wasnt", "wasn't", "free"}
_CONCERN = re.compile(r"\b(worse|worsening|bad|terrible|awful|sick|unwell|pain|painful|hurts?|hurting|bleed\w*|blood|scared|worried|"
                      r"help|emergency|dying|ill|trouble)\b", re.I)


def _words_before(text: str, pos: int, n: int = 5) -> list[str]:
    left = re.split(r"[.;!?\n]|\bbut\b|\bhowever\b", text[:pos].lower())[-1]  # stop at sentence breaks and "but"
    return re.findall(r"[a-z']+", left)[-n:]


def negated(text: str, pos: int) -> bool:
    return any(w in _NEGATORS for w in _words_before(text, pos))


def concepts_in(text: str) -> list[Concept]:
    """Concepts the message mentions without negating them ('no swelling' does not count)."""
    found: list[Concept] = []
    for c in CONCEPTS:
        for m in c.message.finditer(text):
            if not negated(text, m.start()):
                found.append(c)
                break
    return found


def sounds_severe(text: str) -> bool:
    return any(not negated(text, m.start()) for m in _SEVERE.finditer(text))


# ---------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Rule:
    id: str
    level: str                 # urgent | same_day
    concept: str | None        # a Concept id, or None for the word-overlap fallback
    paper_symptom: str | None  # the paper's own words (None for universal rules)
    action: str                # what the paper says to do
    needs_severity: bool = False
    tokens: tuple[str, ...] = ()   # fallback: words that must appear


_STOP = set("a an the to of and or in on at for with by from as if so than then you your are is be more have has feel get any".split())


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3 and w not in _STOP))


def rules_from_paper(ex: ExtractionResult) -> list[Rule]:
    rules: list[Rule] = []
    for n, sign in enumerate(ex.warning_signs):
        text = sign.symptom
        level = URGENT if re.search(r"911|emergency", f"{sign.action} {sign.symptom}", re.I) else SAME_DAY
        matched = [c for c in CONCEPTS if c.paper.search(text)]
        severe_text = bool(re.search(r"severe|serious", text, re.I))
        for c in matched:
            rules.append(Rule(f"paper{n}:{c.id}", level, c.id, sign.symptom, sign.action,
                              needs_severity=(severe_text and c.id in SEVERE_ONLY)))
        if not matched and _tokens(text):
            rules.append(Rule(f"paper{n}:words", level, None, sign.symptom, sign.action, tokens=_tokens(text)))
    return rules


@dataclass(frozen=True)
class Flag:
    level: str            # urgent | same_day | review
    rule_id: str
    title: str
    detail: str
    action: str = ""      # the paper's own instruction, shown to the patient
    clarify_911: bool = False   # downgraded because it did not sound severe
    short: str = ""            # the phrase shown to the patient, e.g. "More swelling in your feet, ankles or belly"


UNIVERSAL_ACTION = "Call 911"


def evaluate_message(text: str, rules: list[Rule]) -> list[Flag]:
    """All flags a message raises. Highest level first. Empty if nothing was raised."""
    flags: dict[str, Flag] = {}
    mentioned = concepts_in(text)
    severe = sounds_severe(text)
    ids = {c.id for c in mentioned}

    def add(flag: Flag) -> None:
        old = flags.get(flag.rule_id)
        if old is None or _rank(flag.level) < _rank(old.level):
            flags[flag.rule_id] = flag

    # universal emergencies
    for c in mentioned:
        if c.id in UNIVERSAL_URGENT or (c.id in SEVERE_ONLY and severe and c.id != "belly_pain"):
            add(Flag(URGENT, f"universal:{c.id}", f"Possible emergency: {c.label}", f"Patient wrote: “{text.strip()[:200]}”",
                     UNIVERSAL_ACTION, short=c.label))

    # the patient's own paper
    for r in rules:
        hit = (r.concept in ids) if r.concept else (len(set(r.tokens) & _message_tokens(text)) >= min(2, len(r.tokens)) and _no_negation_for(text, r.tokens))
        if not hit:
            continue
        level, clarify = r.level, False
        if r.level == URGENT and r.needs_severity and not severe:
            level, clarify = SAME_DAY, True
        add(Flag(level, r.id, f"{'Emergency sign' if level == URGENT else 'Warning sign'} from their paper: {r.paper_symptom}",
                 f"Patient wrote: “{text.strip()[:200]}”. Their paper says: {r.action}.", r.action, clarify_911=clarify,
                 short=r.paper_symptom or ""))

    # The paper's own urgent rule is more specific than the built-in one for the same symptom: keep just that one.
    paper_urgent = {k.split(":")[-1] for k, f in flags.items() if k.startswith("paper") and f.level == URGENT}
    for key in [k for k in flags if k.startswith("universal:") and k.split(":")[-1] in paper_urgent]:
        del flags[key]
    return sorted(flags.values(), key=lambda f: _rank(f.level))


def _rank(level: str) -> int:
    return {URGENT: 0, SAME_DAY: 1, REVIEW: 2}[level]


def _message_tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z]+", text.lower()))


def _no_negation_for(text: str, tokens: tuple[str, ...]) -> bool:
    low = text.lower()
    for t in tokens:
        i = low.find(t)
        if i >= 0 and negated(low, i):
            return False
    return True


def sounds_concerning(text: str) -> bool:
    """Worrying wording that no rule recognised: a person should read it."""
    return any(not negated(text, m.start()) for m in _CONCERN.finditer(text))


# ---------------------------------------------------------------------------------------------------------------
# weight rules, read from the paper: "Gain more than 3 pounds in 1 day or 5 pounds in 1 week"
@dataclass(frozen=True)
class WeightRule:
    pounds: float
    days: int
    paper_text: str
    action: str


_WEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:pounds?|lbs?\.?)\s+(?:in|within|over)\s+(?:(a|one|1)|(\d+))\s*(day|week)s?", re.I)


def weight_rules(ex: ExtractionResult) -> list[WeightRule]:
    out: list[WeightRule] = []
    for sign in ex.warning_signs:
        for m in _WEIGHT.finditer(sign.symptom):
            n = 1 if m.group(2) else int(m.group(3))
            days = n * (7 if m.group(4).lower() == "week" else 1)
            out.append(WeightRule(float(m.group(1)), days, sign.symptom, sign.action))
    return out


def check_weight(rules: list[WeightRule], history: dict[int, float], day: int, pounds: float) -> list[Flag]:
    """``history`` maps day index -> pounds for EARLIER days. A gain strictly above the paper's number raises a flag."""
    flags: list[Flag] = []
    for r in sorted(rules, key=lambda r: r.days):
        if r.days == 1:
            base = history.get(day - 1)
        else:
            window = [w for d, w in history.items() if day - r.days <= d < day]
            base = min(window) if window else None
        if base is None:
            continue
        gain = round(pounds - base, 1)
        if gain > r.pounds:
            urgent = bool(re.search(r"911", r.action))
            flags.append(Flag(URGENT if urgent else SAME_DAY, f"weight:{r.days}d", f"Weight gain: {gain:g} lb in {'1 day' if r.days == 1 else f'{r.days} days'}",
                              f"Weight today {pounds:g} lb, earlier {base:g} lb. Their paper says: {r.action} if “{r.paper_text}”.", r.action,
                              short=f"Weight up {gain:g} lb in {'1 day' if r.days == 1 else f'{r.days} days'}"))
    return flags[:1]  # one event, one alert: the stricter window wins


_WEIGHT_NUMBER = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d)?)(?![\d.])\s*(kg|kgs|kilos?|lbs?\.?|pounds?)?", re.I)


def looks_like_weight(text: str) -> bool:
    """'172', '172 lb', 'weight 172', '78 kg'. Not 'my blood sugar is 150'."""
    return bool(re.search(r"weigh|\blbs?\b|pounds?|\bkgs?\b|kilos?", text, re.I)) or bool(re.fullmatch(r"\s*\d{2,3}(\.\d)?\s*", text))


def parse_weight(text: str) -> float | None:
    """A body weight in pounds from a reply like '172', '172.5 lb' or '78 kg'. None if no plausible number."""
    for m in _WEIGHT_NUMBER.finditer(text):
        value, unit = float(m.group(1)), (m.group(2) or "").lower()
        if unit.startswith(("kg", "kilo")):
            value = round(value * 2.20462, 1)
        if 60 <= value <= 700:
            return value
    return None


# ---------------------------------------------------------------------------------------------------------------
_YES = re.compile(r"^\s*[✅👍]|^\s*(y|yes|yep|yeah|yup|ya|taken|took|done|ok|okay|sure)\b|\b(i )?(took|have taken|already took|did take|just took)\b", re.I)
_NO = re.compile(r"^\s*(n|no|nope|not yet|skip|skipped|missed|forgot)\b|didn'?t take|did not take|can'?t take|couldn'?t|forgot|ran out|run out|out of (my )?(pills|medicine|meds)", re.I)
_RAN_OUT = re.compile(r"ran out|run out|out of (my )?(pills|medicine|meds)|don'?t have (any|my)", re.I)
_ALL_CLEAR = re.compile(r"^\s*(no|none|nothing|nope|fine|good|ok|okay|all good|feeling (good|fine|ok|okay|great)|i'?m (fine|good|ok|okay))\b|no symptoms|nothing (new|wrong)|feel(ing)? (good|fine|great|ok|okay)", re.I)


def says_yes(text: str) -> bool:
    return bool(_YES.search(text)) and not says_no(text)


def says_no(text: str) -> bool:
    return bool(_NO.search(text))


def ran_out(text: str) -> bool:
    return bool(_RAN_OUT.search(text))


def says_all_clear(text: str) -> bool:
    return bool(_ALL_CLEAR.search(text))

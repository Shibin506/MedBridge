import pytest

from app import redflags as rf
from app.demo import DemoExtractionClient
from app.extractor import Extractor
from app.schemas import ExtractionResult
from conftest import SAMPLES


def extraction(name="01_heart_failure.txt") -> ExtractionResult:
    ex = Extractor(client=DemoExtractionClient()).extract((SAMPLES / name).read_text(encoding="utf-8"))
    for g in (ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions):
        for i in g:
            i.patient_confirmed = True
    return ex


@pytest.fixture(scope="module")
def heart_rules():
    return rf.rules_from_paper(extraction())


def levels(text, rules):
    return [f.level for f in rf.evaluate_message(text, rules)]


# ---------- negation ----------
@pytest.mark.parametrize("text", [
    "no chest pain", "I do not have chest pain", "No swelling, no dizziness", "without any dizziness",
    "I'm fine. No chest pain and no trouble breathing", "never had a fever", "denies any bleeding",
    "no swelling or dizziness today", "nothing hurts", "I don't feel dizzy",
])
def test_negated_symptoms_raise_nothing(text, heart_rules):
    assert rf.evaluate_message(text, heart_rules) == [], text


def test_negation_does_not_leak_across_sentences_or_but(heart_rules):
    assert levels("No swelling. I have chest pain.", heart_rules) == [rf.URGENT]
    assert levels("no dizziness but my ankles are swollen", heart_rules) == [rf.SAME_DAY]


# ---------- universal emergencies ----------
@pytest.mark.parametrize("text", [
    "I have chest pain", "my chest is hurting", "there is pressure in my chest", "I fainted this morning", "I passed out",
    "my face is drooping and my speech is slurred", "I am vomiting blood", "coughing up blood", "my throat is closing",
    "I want to kill myself", "I can't breathe", "gasping for air and short of breath",
])
def test_universal_emergencies_are_urgent_even_with_no_paper(text):
    flags = rf.evaluate_message(text, [])
    assert flags and flags[0].level == rf.URGENT, text


# ---------- rules built from the patient's own paper ----------
def test_rules_are_built_from_the_confirmed_warning_signs(heart_rules):
    by_id = {r.id: r for r in heart_rules}
    assert by_id["paper4:chest_pain"].level == rf.URGENT          # "Call 911"
    assert by_id["paper0:swelling" if "paper0:swelling" in by_id else "paper1:swelling"].level == rf.SAME_DAY  # "Call your doctor"
    assert any(r.concept == "dizziness" and r.level == rf.SAME_DAY for r in heart_rules)
    assert any(r.concept == "breathing" and r.needs_severity for r in heart_rules)  # "SEVERE trouble breathing"


@pytest.mark.parametrize("text,expected", [
    ("my ankles are swollen", [rf.SAME_DAY]),
    ("feeling really dizzy", [rf.SAME_DAY]),
    ("my heart is racing", [rf.SAME_DAY]),
    ("I needed more pillows to sleep", [rf.SAME_DAY]),
    ("I have chest pain", [rf.URGENT]),
    ("everything is fine today", []),
    ("just took my pills", []),
])
def test_paper_rules_set_the_level(text, expected, heart_rules):
    got = levels(text, heart_rules)
    assert got[:1] == expected[:1] and (not expected or got), (text, got)


def test_mild_breathing_trouble_is_downgraded_with_a_911_hint(heart_rules):
    mild = rf.evaluate_message("a bit short of breath", heart_rules)
    assert mild and all(f.level == rf.SAME_DAY for f in mild)
    assert any(f.clarify_911 for f in mild)
    severe = rf.evaluate_message("severe trouble breathing, I can't catch my breath", heart_rules)
    assert severe[0].level == rf.URGENT


def test_one_alert_for_one_event(heart_rules):
    flags = rf.evaluate_message("I have chest pain", heart_rules)
    assert len(flags) == 1 and flags[0].rule_id.startswith("paper")  # the paper's rule, not a duplicate universal one


def test_signs_that_match_no_concept_fall_back_to_word_overlap():
    ex = extraction()
    ex.warning_signs[0].symptom = "Your leg smells strange or leaks green fluid"
    ex.warning_signs[0].action = "Call the office"
    rules = rf.rules_from_paper(ex)
    assert any(r.id.endswith(":words") for r in rules)
    assert levels("my leg leaks green fluid", rules)[:1] == [rf.SAME_DAY]
    assert levels("my leg looks fine", rules) == []


def test_hip_paper_rules_cover_its_own_signs():
    rules = rf.rules_from_paper(extraction("03_hip_replacement.txt"))
    assert levels("redness and drainage at my incision", rules)[:1] == [rf.SAME_DAY]
    assert levels("pain in my calf and it is swollen", rules)[:1] == [rf.SAME_DAY]
    assert levels("coughing blood", rules)[:1] == [rf.URGENT]


# ---------- vague worry ----------
@pytest.mark.parametrize("text,expected", [
    ("I feel really bad today", True), ("something hurts", True), ("I am worried", True), ("I'm scared", True),
    ("not worried at all", False), ("I feel good", False), ("no pain", False), ("banana", False),
])
def test_concerning_wording(text, expected):
    assert rf.sounds_concerning(text) is expected


# ---------- weight ----------
@pytest.mark.parametrize("text,expected", [
    ("172", 172.0), ("172.5 lb", 172.5), ("weight is 180 pounds", 180.0), ("78 kg", 172.0), ("about 165lbs", 165.0),
    ("no number here", None), ("12", None), ("1200", None), ("I took 2 pills", None),
])
def test_parse_weight(text, expected):
    assert rf.parse_weight(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("172", True), ("weight 172", True), ("172 lbs", True), ("my blood sugar is 150", False), ("it is 150 today", False),
])
def test_only_weight_looking_messages_count_outside_the_check_in(text, expected):
    assert rf.looks_like_weight(text) is expected


def test_weight_rules_are_read_from_the_paper():
    rules = rf.weight_rules(extraction())
    assert [(r.pounds, r.days) for r in rules] == [(3.0, 1), (5.0, 7)]
    assert rf.weight_rules(extraction("03_hip_replacement.txt")) == []


def test_weight_gain_must_be_strictly_more_than_the_paper_number():
    rules = rf.weight_rules(extraction())
    assert rf.check_weight(rules, {0: 170.0}, 1, 173.0) == []                     # exactly 3 lb: not "more than 3"
    flag = rf.check_weight(rules, {0: 170.0}, 1, 173.1)
    assert len(flag) == 1 and flag[0].level == rf.SAME_DAY and "3.1 lb in 1 day" in flag[0].short


def test_week_rule_uses_the_lowest_weight_in_the_window():
    rules = rf.weight_rules(extraction())
    history = {0: 170.0, 1: 172.0, 2: 173.0, 3: 174.0}
    assert rf.check_weight(rules, history, 4, 174.5) == []                         # +0.5 vs yesterday, +4.5 vs the week low
    flags = rf.check_weight(rules, history, 4, 175.5)                              # +5.5 vs the week low, +1.5 vs yesterday
    assert len(flags) == 1 and "7 days" in flags[0].short


def test_no_history_means_no_weight_flag():
    assert rf.check_weight(rf.weight_rules(extraction()), {}, 3, 200.0) == []


def test_both_windows_exceeded_is_reported_once_with_the_stricter_window():
    flags = rf.check_weight(rf.weight_rules(extraction()), {0: 170.0}, 1, 180.0)
    assert len(flags) == 1 and "1 day" in flags[0].short


# ---------- yes / no ----------
@pytest.mark.parametrize("text,yes,no", [
    ("yes", True, False), ("Y", True, False), ("took them", True, False), ("done", True, False), ("👍", True, False),
    ("no", False, True), ("not yet", False, True), ("I forgot", False, True), ("couldn't take it", False, True), ("I ran out", False, True),
    ("I did not take it", False, True), ("maybe", False, False),
])
def test_yes_no(text, yes, no):
    assert rf.says_yes(text) is yes and rf.says_no(text) is no

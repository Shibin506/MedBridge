"""A labelled set of realistic patient messages, checked against all four sample papers.

This is the evidence behind the claim "no emergency message in our test set is missed". Every message here was
written to sound like a real text (typos, slang, past tense, negations). If a rule change makes one fail,
the change is wrong, or the expectation must be argued for in review.
"""

import pytest

from app import redflags as rf
from app.demo_patients import confirmed_extraction

PAPERS = ("01_heart_failure.txt", "02_pneumonia.txt", "03_hip_replacement.txt", "04_gallbladder_surgery.txt")
RULES = {p: rf.rules_from_paper(confirmed_extraction(p)) for p in PAPERS}
WEIGHT = {p: rf.weight_rules(confirmed_extraction(p)) for p in PAPERS}

# Must ALWAYS be an emergency ("call 911"), whatever the paper says.
EMERGENCY = [
    "I have chest pain", "my chest feels tight and heavy", "crushing pressure in my chest", "chest hurts really bad",
    "pain in my chest and left arm", "I think I'm having a heart attack", "chest pressure won't go away",
    "I passed out", "I fainted this morning", "I blacked out", "I collapsed in the kitchen",
    "my face is drooping and my speech is slurred", "numbness on one side of my body", "I can't move my left arm",
    "sudden confusion and trouble speaking", "suddenly weak on my right side",
    "I'm coughing up blood", "I threw up blood", "vomiting blood", "there is blood in my vomit", "coughed up some blood",
    "my throat is closing", "my lips are swelling and I can't swallow", "my tongue is swollen",
    "I want to kill myself", "I don't want to live anymore", "I'm thinking about hurting myself", "I wish I was dead",
    "my lips are turning blue", "my fingertips are blue",
    "can't breathe at all", "cant breath", "I'm gasping for air", "severe trouble breathing", "hard to breathe, really struggling",
    "I can't catch my breath and it's getting worse",
    "I had a seizure", "worst headache of my life", "coughing up pink foamy stuff",
]

# Must raise NOTHING (no alert, no worry): negations and ordinary replies.
CALM = [
    "no chest pain", "I don't have any chest pain today", "no chest pain, no swelling, feeling fine", "my chest is clear",
    "I feel fine", "all good today", "none", "NONE", "nothing today", "no problems", "I have no shortness of breath",
    "denies chest pain", "never had chest pain", "slept well, ate breakfast", "my chest x-ray was normal", "thanks!",
    "ok", "172 and no symptoms", "no dizziness, no swelling, no trouble breathing", "I would never hurt myself",
    "not dizzy and not short of breath", "yes", "took them", "feeling great",
]

# Must reach a PERSON at least ("please read"), even when the paper does not list it: vague worry is never reassured.
AT_LEAST_REVIEW = [
    "I feel really bad today", "something is wrong", "I'm scared", "I feel awful", "I don't feel right",
    "I'm so tired and weak", "I feel terrible", "fever of 102", "vomiting and can't keep my pills down",
    "my stomach hurts a lot", "I have a cough that is getting worse", "my wound is bleeding a little",
    "I'm not feeling well", "I can't get up", "I have chills",
]

# What THIS patient's paper says decides these.
PAPER_SPECIFIC = [
    ("01_heart_failure.txt", "my ankles are swollen", rf.SAME_DAY),
    ("01_heart_failure.txt", "my legs are more swollen than yesterday", rf.SAME_DAY),
    ("01_heart_failure.txt", "my belly is swollen", rf.SAME_DAY),
    ("01_heart_failure.txt", "very dizzy today", rf.SAME_DAY),
    ("01_heart_failure.txt", "I need 3 pillows to sleep now", rf.SAME_DAY),
    ("01_heart_failure.txt", "a bit short of breath walking upstairs", rf.SAME_DAY),          # the paper's 911 sign says SEVERE
    ("02_pneumonia.txt", "I have a cough that is getting worse", rf.SAME_DAY),
    ("02_pneumonia.txt", "vomiting and can't keep my pills down", rf.SAME_DAY),
    ("02_pneumonia.txt", "I have a rash all over", rf.SAME_DAY),
    ("02_pneumonia.txt", "fever of 102", rf.SAME_DAY),                                        # the paper's 911 sign: a fever that LASTS 48 h
    ("03_hip_replacement.txt", "my incision is red and has drainage", rf.SAME_DAY),
    ("03_hip_replacement.txt", "my calf hurts and is swollen", rf.SAME_DAY),
    ("03_hip_replacement.txt", "my wound is bleeding a little", rf.SAME_DAY),                 # the 911 sign: bleeding that will NOT stop
    ("03_hip_replacement.txt", "the bleeding will not stop, it is soaking the dressing", rf.URGENT),
    ("04_gallbladder_surgery.txt", "yellow skin and eyes", rf.SAME_DAY),
    ("04_gallbladder_surgery.txt", "fever of 102", rf.SAME_DAY),
    ("04_gallbladder_surgery.txt", "severe belly pain", rf.SAME_DAY),
    ("04_gallbladder_surgery.txt", "vomiting and can't keep my pills down", rf.REVIEW),       # 911 only for vomiting BLOOD
]

RANK = {"none": 3, rf.REVIEW: 2, rf.SAME_DAY: 1, rf.URGENT: 0}


def level(text: str, paper: str) -> str:
    flags = rf.evaluate_message(text, RULES[paper]) + rf.check_reported_gain(WEIGHT[paper], text)
    if flags:
        return min((f.level for f in flags), key=RANK.get)
    return rf.REVIEW if rf.sounds_concerning(text) else "none"


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("text", EMERGENCY)
def test_emergencies_are_never_missed(text, paper):
    assert level(text, paper) == rf.URGENT, f"{text!r} with {paper}"


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("text", CALM)
def test_calm_messages_raise_nothing(text, paper):
    assert level(text, paper) == "none", f"{text!r} with {paper}"


@pytest.mark.parametrize("paper", PAPERS)
@pytest.mark.parametrize("text", AT_LEAST_REVIEW)
def test_worry_always_reaches_a_person(text, paper):
    assert RANK[level(text, paper)] <= RANK[rf.REVIEW], f"{text!r} with {paper}"


@pytest.mark.parametrize("paper,text,expected", PAPER_SPECIFIC)
def test_the_patients_own_paper_decides(paper, text, expected):
    assert level(text, paper) == expected


@pytest.mark.parametrize("text,expected", [
    ("I gained 4 pounds since yesterday", rf.SAME_DAY),     # > 3 lb in 1 day
    ("gained 6 lbs this week", rf.SAME_DAY),                # > 5 lb in a week
    ("gained 4 lbs this week", "none"),                     # not over the weekly limit
    ("I gained 4 pounds", rf.SAME_DAY),                     # no time given: the strictest limit is used
    ("I haven't gained 4 pounds", "none"),
])
def test_a_stated_weight_gain_is_checked_against_the_paper(text, expected):
    assert level(text, "01_heart_failure.txt") == expected


def test_the_set_is_big_enough_to_mean_something():
    assert len(EMERGENCY) >= 35 and len(CALM) >= 20 and len(AT_LEAST_REVIEW) >= 12

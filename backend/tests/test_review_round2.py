"""Replays what the REAL model got wrong on the gallbladder paper: it dropped '2 tablets', the 'until ...' on the
stopped medicines, and the shower permission. Our checks must now notice each one."""

import pytest

from app.coverage import sentences, uncovered_lines
from app.demo import GALLBLADDER
from app.schemas import ExtractionDraft
from app.verify import verify
from conftest import SAMPLES

import copy


@pytest.fixture
def gall_text():
    return (SAMPLES / "04_gallbladder_surgery.txt").read_text(encoding="utf-8")


def real_model_output() -> ExtractionDraft:
    """The demo data, degraded exactly like the real Groq run."""
    data = copy.deepcopy(GALLBLADDER)
    for m in data["medications"]:
        if m["name"] == "Tylenol":
            m["dose"] = "500 mg"                      # '2 tablets' lost
        if m["status"] == "stop":
            m["duration"] = None                      # 'until your surgeon says it is safe' lost
    data["restrictions"] = [r for r in data["restrictions"] if "shower" not in r["instruction"]]
    data["restrictions"].append({"category": "wound_care", "instruction": "Do not soak in a bath for 2 weeks",
                                 "source_quote": "Do not soak in a bath for 2 weeks."})
    return ExtractionDraft.model_validate(data)


def test_the_good_demo_data_has_no_findings(gall_text):
    r = verify(ExtractionDraft.model_validate(GALLBLADDER), gall_text)
    assert r.items_needing_confirmation == 0 and r.uncovered_lines == []


def test_dropped_tablet_count_is_flagged(gall_text):
    r = verify(real_model_output(), gall_text)
    tylenol = next(m for m in r.medications if m.name == "Tylenol")
    assert tylenol.needs_confirmation
    assert any("take 2 at a time" in i for i in tylenol.issues)


def test_tablet_count_rules(gall_text):
    def flagged(dose, quote="Tylenol 500 mg - take 2 tablets by mouth every 6 hours", freq="every 6 hours", instr=None):
        data = copy.deepcopy(GALLBLADDER)
        m = next(x for x in data["medications"] if x["name"] == "Tylenol")
        m.update(dose=dose, frequency=freq, instructions=instr, source_quote=quote)
        # keep the quote groundable for this unit check by testing the verifier on a custom document
        r = verify(ExtractionDraft.model_validate({**data, "medications": [m], "follow_ups": [], "warning_signs": [],
                                                    "restrictions": []}), quote)
        return any("at a time" in i for i in r.medications[0].issues)

    assert flagged("500 mg") is True
    assert flagged("500 mg, 2 tablets") is False
    assert flagged("2 tablets of 500 mg") is False
    assert flagged("500 mg", instr="take 2 tablets") is False            # mentioned in the instructions instead
    assert flagged("500 mg", quote="Tylenol 500 mg - take 1 tablet every 6 hours") is False   # '1 tablet' is the usual case
    assert flagged("1 mg", quote="Drug 1 mg - take two tablets daily", freq="daily") is True  # number words count
    assert flagged("0.5 mg, 1.5 tablets", quote="Drug 0.5 mg - take 1.5 tablets daily", freq="daily") is False


def test_dropped_until_condition_on_stopped_medicines_is_flagged(gall_text):
    r = verify(real_model_output(), gall_text)
    for name in ("Advil", "Aspirin"):
        med = next(m for m in r.medications if m.name == name)
        assert med.needs_confirmation, name
        assert any("until your surgeon says it is safe" in i and "temporary" in i for i in med.issues), med.issues


def test_until_kept_anywhere_in_the_item_is_accepted(gall_text):
    data = copy.deepcopy(GALLBLADDER)
    for m in data["medications"]:
        if m["status"] == "stop":
            m["duration"] = None
            m["instructions"] = "until your surgeon says it is safe"
    assert verify(ExtractionDraft.model_validate(data), gall_text).items_needing_confirmation == 0


def test_dropped_shower_permission_shows_up_as_an_unused_line(gall_text):
    r = verify(real_model_output(), gall_text)
    assert r.uncovered_lines == ["You may shower after 48 hours."]


# ---------- the sentence splitter ----------
def test_sentences_join_wrapped_lines_and_do_not_cut_at_dr():
    doc = ("Reason: you were admitted because of worsening shortness of breath caused by\n"
           "congestive heart failure (your heart was weak).\n"
           "1. Furosemide 40 mg - take it. This is a\n   water pill to remove extra fluid.\n"
           "Follow-up appointments\n - Primary care, Dr. Singh - in 5 to 7 days.\n")
    got = sentences(doc)
    assert "Reason: you were admitted because of worsening shortness of breath caused by congestive heart failure (your heart was weak)." in got
    assert "Furosemide 40 mg - take it." in got and "This is a water pill to remove extra fluid." in got
    assert "Follow-up appointments" in got and "Primary care, Dr. Singh - in 5 to 7 days." in got


def test_headings_metadata_and_banners_are_not_reported():
    doc = ("*** SYNTHETIC DOCUMENT - FICTIONAL PATIENT ***\nLAKESIDE MEDICAL CENTER - Hospital Medicine\n"
           "Patient: Daniel Reyes   DOB: 1958 (age 67)\nFOLLOW-UP\n")
    assert uncovered_lines(doc, {}) == []


def test_a_covered_sentence_is_not_reported_but_a_new_one_is():
    doc = "Take the blue pill every morning with food.\nYou may drive again after two weeks of rest.\n"
    extracted = {"medications": [{"name": "Blue pill", "instructions": "every morning with food", "source_quote": "Take the blue pill every morning with food."}]}
    assert uncovered_lines(doc, extracted) == ["You may drive again after two weeks of rest."]


def test_at_most_twelve_lines_are_reported():
    doc = "\n".join(f"Remember to complete task number {n} with great care today." for n in range(30))
    assert len(uncovered_lines(doc, {})) == 12


def test_the_api_returns_uncovered_lines(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("MEDBRIDGE_DEMO", "1")
    text = (SAMPLES / "01_heart_failure.txt").read_bytes()
    body = TestClient(app).post("/extract", files={"file": ("a.txt", text, "text/plain")}).json()
    assert any("Fluid was removed" in line for line in body["uncovered_lines"])


# ---- round 3: excerpt centred on the match, precautions are not alerts --------------------
def test_interaction_excerpt_shows_the_matching_word():
    from app.safety import EXCERPT_CHARS, _mention
    filler = "Table 3: Drugs that Can Increase the Risk of Bleeding " + "Anticoagulants heparin enoxaparin " * 12
    text = filler + "Non-steroidal Anti-inflammatory Agents such as ibuprofen, naproxen " + filler + "."
    out = _mention(text, ["ibuprofen"])
    assert out and "ibuprofen" in out
    assert len(out) <= EXCERPT_CHARS + 2   # plus the two ellipses


def test_short_sentence_is_unchanged():
    from app.safety import _mention
    assert _mention("Warfarin interacts with ibuprofen. Other.", ["ibuprofen"]) == "Warfarin interacts with ibuprofen."


def test_do_not_drive_is_not_a_call_action():
    from app import redflags as rf
    assert rf.is_call_action("Call 911")
    assert rf.is_call_action("Call your doctor")
    assert rf.is_call_action("Go to the emergency room")
    assert not rf.is_call_action("Do not drive")
    assert not rf.is_call_action("Avoid alcohol")
    assert not rf.is_call_action("")

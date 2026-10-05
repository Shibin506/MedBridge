import copy

import pytest

from app.demo import GALLBLADDER, HIP, DemoExtractionClient, DemoLabelSource
from app.extractor import Extractor
from app.safety import SafetyChecker
from app.schemas import ExtractionDraft
from app.totals import LABEL_MAX_MG, _as_needed_max, mg_per_dose, paper_limit
from app.verify import verify
from conftest import SAMPLES


def report_for(name):
    text = (SAMPLES / name).read_text(encoding="utf-8")
    ex = Extractor(client=DemoExtractionClient()).extract(text)
    return ex, SafetyChecker(labels=DemoLabelSource()).check(ex)


def build(data: dict, text: str):
    ex = verify(ExtractionDraft.model_validate(data), text)
    return ex, SafetyChecker().check(ex)


def test_gallbladder_paper_can_exceed_the_label_maximum():
    _, r = report_for("04_gallbladder_surgery.txt")
    (f,) = r.daily_totals
    assert (f.total_mg, f.limit_mg, f.limit_source) == (5300, LABEL_MAX_MG, "common label maximum")
    assert {c.name: c.mg_per_day for c in f.contributors} == {"Tylenol": 4000, "Percocet": 1300}
    percocet = next(c for c in f.contributors if c.name == "Percocet")
    assert percocet.as_needed and percocet.mg_per_dose == 325 and percocet.doses_per_day == 4
    assert "5,300 mg" in f.message and "Ask your pharmacist" in f.message


@pytest.mark.parametrize("name", ["01_heart_failure.txt", "02_pneumonia.txt", "03_hip_replacement.txt"])
def test_other_papers_have_no_daily_total_warning(name):
    _, r = report_for(name)
    assert r.daily_totals == []


def test_exactly_at_the_limit_is_not_a_warning():
    ex, r = report_for("03_hip_replacement.txt")  # 1,000 mg x 3 a day = 3,000 and the paper says no more than 3,000
    assert paper_limit(ex) == 3000 and r.daily_totals == []


def test_a_limit_stated_on_the_paper_beats_the_label_maximum():
    text = (SAMPLES / "04_gallbladder_surgery.txt").read_text(encoding="utf-8")
    data = copy.deepcopy(GALLBLADDER)
    data["restrictions"].append({"category": "medication_limit", "source_quote": "No lifting more than 10 pounds for 4 weeks.",
                                 "instruction": "Take no more than 3,000 mg of acetaminophen (Tylenol) in one day"})
    ex, r = build(data, text)
    (f,) = r.daily_totals
    assert f.limit_mg == 3000 and f.limit_source == "your paper" and "what your paper says" in f.message


def test_a_lower_dose_stays_under_the_limit():
    text = (SAMPLES / "04_gallbladder_surgery.txt").read_text(encoding="utf-8")
    data = copy.deepcopy(GALLBLADDER)
    next(m for m in data["medications"] if m["name"] == "Tylenol").update(dose="500 mg, 1 tablet")  # 4 x 500 = 2,000 (+1,300)
    _, r = build(data, text)
    assert r.daily_totals == []


def test_stopped_acetaminophen_is_not_counted():
    text = (SAMPLES / "04_gallbladder_surgery.txt").read_text(encoding="utf-8")
    data = copy.deepcopy(GALLBLADDER)
    next(m for m in data["medications"] if m["name"] == "Tylenol").update(status="stop")
    _, r = build(data, text)
    assert r.daily_totals == []  # only Percocet's 1,300 remains


def test_something_we_cannot_read_is_reported_not_guessed():
    text = (SAMPLES / "04_gallbladder_surgery.txt").read_text(encoding="utf-8")
    data = copy.deepcopy(GALLBLADDER)
    next(m for m in data["medications"] if m["name"] == "Percocet").update(dose="1 tablet")  # no strength given
    _, r = build(data, text)
    assert r.daily_totals == []  # Tylenol alone is exactly 4,000
    assert any("could not add up the acetaminophen in Percocet" in n for n in r.notes)


@pytest.mark.parametrize("dose,ingredients,expected", [
    ("500 mg", ["acetaminophen"], 500),
    ("500 mg, 2 tablets", ["acetaminophen"], 1000),
    ("1,000 mg", ["acetaminophen"], 1000),
    ("325 mg, two tablets", ["acetaminophen"], 650),
    ("5/325 mg, 1 tablet", ["oxycodone", "acetaminophen"], 325),
    ("5/325 mg, 2 tablets", ["oxycodone", "acetaminophen"], 650),
    ("325/5 mg", ["acetaminophen", "oxycodone"], 325),
    ("1 tablet", ["acetaminophen"], None),
    ("5 mg", ["oxycodone", "acetaminophen"], None),            # a combination without both strengths: do not guess
    ("5/325/30 mg", ["oxycodone", "acetaminophen"], None),     # three strengths for two ingredients: do not guess
])
def test_milligrams_per_dose(dose, ingredients, expected):
    from app.schemas import Medication
    m = Medication(name="X", dose=dose, route=None, frequency="daily", duration=None, purpose=None, instructions=None,
                   status="new", source_quote="x", grounded=True, needs_confirmation=False)
    assert mg_per_dose(m, ingredients) == expected


@pytest.mark.parametrize("freq,expected", [
    ("every 6 hours ONLY IF your pain is severe", 4), ("every 4-6 hours as needed", 6), ("every 8 hours", 3),
    ("twice daily as needed", 2), ("three times a day", 3), ("as needed", None), (None, None),
])
def test_most_doses_a_day_for_as_needed_medicines(freq, expected):
    assert _as_needed_max(freq) == expected


def test_it_reaches_the_screen_through_the_api(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    monkeypatch.setenv("MEDBRIDGE_DEMO", "1")
    c = TestClient(app)
    text = (SAMPLES / "04_gallbladder_surgery.txt").read_bytes()
    ex = c.post("/extract", files={"file": ("a.txt", text, "text/plain")}).json()
    body = {"extraction": ex, "acknowledged_unclear": True, "acknowledged_review": True}
    out = c.post("/safety", json=body).json()
    assert out["daily_totals"][0]["total_mg"] == 5300

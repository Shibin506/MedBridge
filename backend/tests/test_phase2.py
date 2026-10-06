import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.demo import DemoExtractionClient, DemoPlanClient
from app.extractor import Extractor
from app.main import app
from app.plan import PlanError, PlanGenerator, build_plan_input, check_plan, readiness_problems
from app.schemas import PlanDraft, PlanRequest
from conftest import SAMPLES, draft_for_heart_failure


def extract_sample(name: str):
    text = (SAMPLES / name).read_text(encoding="utf-8")
    return Extractor(client=DemoExtractionClient()).extract(text)


def confirm_everything(ex):
    for group in (ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions):
        for item in group:
            item.patient_confirmed = True
    return ex


def good_draft(ex) -> PlanDraft:
    """What a well-behaved model would return for `ex` (built by the demo writer)."""
    req = PlanRequest(extraction=ex)
    content = (
        "Target language: English (en)\n\n<confirmed_data>\n"
        + json.dumps(build_plan_input(ex))
        + "\n</confirmed_data>"
    )
    return DemoPlanClient().messages.parse(messages=[{"content": content}]).parsed_output


# ---------- demo data behaves as designed ----------
def test_heart_demo_flags_exactly_the_planted_problems():
    ex = extract_sample("01_heart_failure.txt")
    flagged = {m.name for m in ex.medications if m.needs_confirmation}
    assert flagged == {"Aspirin", "Potassium chloride"}
    potassium = next(m for m in ex.medications if m.name == "Potassium chloride")
    assert potassium.grounded is False  # the made-up medicine was caught
    assert all(i.grounded for g in (ex.follow_ups, ex.warning_signs, ex.restrictions) for i in g)


@pytest.mark.parametrize("name", ["02_pneumonia.txt", "03_hip_replacement.txt"])
def test_other_demo_samples_are_fully_grounded(name):
    ex = extract_sample(name)
    assert ex.items_needing_confirmation == 0, [
        (i.source_quote, i.issues)
        for g in (ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions)
        for i in g
        if i.needs_confirmation
    ]


def test_stop_medicine_without_dose_is_not_flagged():
    ex = extract_sample("01_heart_failure.txt")
    ibuprofen = next(m for m in ex.medications if m.name == "Ibuprofen")
    assert ibuprofen.status == "stop" and ibuprofen.needs_confirmation is False


# ---------- the gate ----------
def test_gate_blocks_until_flagged_items_confirmed_and_notes_acknowledged():
    ex = extract_sample("01_heart_failure.txt")
    problems = readiness_problems(PlanRequest(extraction=ex))
    assert any("2 item(s) still need your check" in p for p in problems)
    assert any("notes" in p for p in problems)

    for m in ex.medications:
        if m.needs_confirmation:
            m.patient_confirmed = True
    assert len(readiness_problems(PlanRequest(extraction=ex, acknowledged_review=True))) == 1  # only the unclear-notes tick left
    assert readiness_problems(PlanRequest(extraction=ex, acknowledged_unclear=True, acknowledged_review=True)) == []


def test_gate_rejects_empty_plan_and_unknown_language():
    ex = extract_sample("01_heart_failure.txt")
    ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions = [], [], [], []
    assert any("nothing to build" in p for p in readiness_problems(PlanRequest(extraction=ex, acknowledged_unclear=True, acknowledged_review=True)))
    ex2 = confirm_everything(extract_sample("03_hip_replacement.txt"))
    assert any("Unsupported language" in p for p in readiness_problems(PlanRequest(extraction=ex2, language="xx")))


# ---------- plan checks ----------
def test_good_plan_passes_checks():
    ex = confirm_everything(extract_sample("01_heart_failure.txt"))
    assert check_plan(good_draft(ex), ex) == []


def test_check_catches_dropped_item():
    ex = confirm_everything(extract_sample("03_hip_replacement.txt"))
    draft = good_draft(ex)
    draft.medications.pop()
    assert any("medications" in p for p in check_plan(draft, ex))


def test_check_catches_invented_item():
    ex = confirm_everything(extract_sample("03_hip_replacement.txt"))
    draft = good_draft(ex)
    draft.medications.append(draft.medications[0].model_copy(update={"id": "med_99"}))
    assert any("medications" in p for p in check_plan(draft, ex))


def test_check_catches_changed_dose_number():
    ex = confirm_everything(extract_sample("03_hip_replacement.txt"))
    draft = good_draft(ex)
    draft.medications[0].how_to_take = "Take 5 mg by mouth twice daily."  # data says 2.5 mg for 35 days
    problems = check_plan(draft, ex)
    assert any("med_0" in p and "numbers" in p for p in problems)


def test_check_catches_softened_emergency():
    ex = confirm_everything(extract_sample("03_hip_replacement.txt"))
    draft = good_draft(ex)
    draft.warning_signs[0].plain_text = "Tell someone if you have trouble breathing."
    assert any("911" in p for p in check_plan(draft, ex))


# ---------- generator: retry + code-owned facts ----------
class ScriptedClient:
    def __init__(self, *drafts):
        self.drafts, self.calls = list(drafts), []
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.drafts.pop(0), stop_reason="end_turn")


def test_generator_retries_once_with_feedback_then_succeeds():
    ex = confirm_everything(extract_sample("03_hip_replacement.txt"))
    good = good_draft(ex)
    bad = good.model_copy(deep=True)
    bad.warning_signs[0].plain_text = "Tell someone."
    client = ScriptedClient(bad, good)
    plan = PlanGenerator(client=client).generate(PlanRequest(extraction=ex))
    assert len(client.calls) == 2
    assert "failed these checks" in client.calls[1]["messages"][0]["content"]
    assert plan.warning_signs[0].emergency is True


def test_generator_gives_up_after_second_failure():
    ex = confirm_everything(extract_sample("03_hip_replacement.txt"))
    bad = good_draft(ex)
    bad.medications.pop()
    with pytest.raises(PlanError):
        PlanGenerator(client=ScriptedClient(bad, bad)).generate(PlanRequest(extraction=ex))


def test_facts_come_from_confirmed_data_and_source_label_is_decided_by_code():
    ex = confirm_everything(extract_sample("01_heart_failure.txt"))
    draft = good_draft(ex)
    draft.medications[0].how_to_take = "Take 40 mg by mouth every morning. 1 tablet."  # keeps its numbers
    plan = PlanGenerator(client=ScriptedClient(draft)).generate(PlanRequest(extraction=ex))
    furosemide, metoprolol = plan.medications[0], plan.medications[1]
    assert (furosemide.name, furosemide.dose, furosemide.status) == ("Furosemide", "40 mg", "new")
    assert furosemide.why_source == "your_paper"  # the paper gave a purpose
    assert metoprolol.why_source == "general_knowledge"  # the model added it, so it is labelled
    ibuprofen = next(m for m in plan.medications if m.name == "Ibuprofen")
    assert ibuprofen.status == "stop"
    assert plan.disclaimer_en.startswith("This plan only explains")


# ---------- API in demo mode ----------
@pytest.fixture
def demo_client(monkeypatch):
    monkeypatch.setenv("MEDBRIDGE_DEMO", "1")
    return TestClient(app)


def test_config_and_samples(demo_client):
    cfg = demo_client.get("/config").json()
    assert cfg["demo"] is True and cfg["languages"]["es"] == "Spanish"
    names = demo_client.get("/samples").json()
    assert "01_heart_failure.txt" in names
    assert "Furosemide" in demo_client.get("/samples/01_heart_failure.txt").json()["text"]
    assert demo_client.get("/samples/..%2Fapp%2Fmain.py").status_code == 404
    assert demo_client.get("/samples/nope.txt").status_code == 404


def test_full_flow_extract_confirm_plan(demo_client):
    text = demo_client.get("/samples/01_heart_failure.txt").json()["text"]
    r = demo_client.post("/extract", files={"file": ("a.txt", text.encode(), "text/plain")})
    assert r.status_code == 200
    ex = r.json()
    assert ex["document_text"] == text

    # 1) unconfirmed -> the server refuses
    r = demo_client.post("/plan", json={"extraction": ex})
    assert r.status_code == 409 and r.json()["detail"]["problems"]

    # 2) patient checks the flagged items and ticks the notes -> plan
    for group in ("medications", "follow_ups", "warning_signs", "restrictions"):
        for item in ex[group]:
            if item["needs_confirmation"]:
                item["patient_confirmed"] = True
    r = demo_client.post("/plan", json={"extraction": ex, "acknowledged_unclear": True, "acknowledged_review": True})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["language"] == "en" and len(plan["medications"]) == 8
    assert any(w["emergency"] for w in plan["warning_signs"])

    # 3) another language
    r = demo_client.post("/plan", json={"extraction": ex, "acknowledged_unclear": True, "acknowledged_review": True, "language": "es"})
    assert r.json()["language_name"] == "Spanish"


def test_plan_reports_information_missing_from_the_paper():
    ex = confirm_everything(extract_sample("01_heart_failure.txt"))
    plan = PlanGenerator(client=ScriptedClient(good_draft(ex))).generate(PlanRequest(extraction=ex))
    by_name = {m.name: m for m in plan.medications}
    assert by_name["Aspirin"].missing_info == ["frequency"]  # the paper never says how often
    assert by_name["Furosemide"].missing_info == []
    assert by_name["Ibuprofen"].missing_info == []  # stop medicines have no dose to miss


def test_route_is_a_standard_clinical_term_and_bad_values_are_rejected():
    ex = extract_sample("01_heart_failure.txt")
    assert {m.route for m in ex.medications} <= {"oral", None}
    assert next(m for m in ex.medications if m.name == "Furosemide").route == "oral"
    from app.schemas import MedicationDraft
    with pytest.raises(ValueError):
        MedicationDraft(name="X", dose=None, route="by mouth", frequency=None, duration=None, purpose=None,
                        instructions=None, status="new", source_quote="x")


def test_demo_plan_says_by_mouth_in_plain_words():
    ex = confirm_everything(extract_sample("01_heart_failure.txt"))
    draft = good_draft(ex)
    assert "by mouth" in draft.medications[0].how_to_take  # plan is plain even though the data says "oral"


def test_gallbladder_demo_sample_is_fully_grounded():
    ex = extract_sample("04_gallbladder_surgery.txt")
    assert ex.items_needing_confirmation == 0, [
        (i.source_quote, i.issues)
        for g in (ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions)
        for i in g if i.needs_confirmation
    ]
    assert len(ex.medications) == 9 and ex.unclear_items


@pytest.mark.parametrize("given,expected", [
    ("for 35 days after surgery", "35 days after surgery"),
    ("For the first 2 weeks, then as needed", "the first 2 weeks, then as needed"),
    ("  for  7 days ", "7 days "),
    ("7 days", "7 days"),
    ("until follow-up", "until follow-up"),
    ("formula for success", "formula for success"),  # only a LEADING word "for" is removed
    (None, None),
])
def test_duration_never_starts_with_for(given, expected):
    from app.schemas import MedicationDraft
    m = MedicationDraft(name="X", dose=None, route=None, frequency=None, duration=given, purpose=None,
                        instructions=None, status="new", source_quote="X")
    assert m.duration == expected


def test_schedule_note_reads_naturally_after_cleaning():
    from app.schedule import build_schedule
    from app.schemas import Medication
    m = Medication(name="Apixaban", dose="2.5 mg", route="oral", frequency="twice daily", duration="for 35 days after surgery",
                   purpose=None, instructions=None, status="new", source_quote="x", grounded=True, needs_confirmation=False)
    assert build_schedule([m]).slots[0].items[0].note == "for 35 days after surgery"


# ---------- review round: numbers, phone numbers, old dose, new categories, review gate ----------
def heart_draft_with(**changes):
    d = draft_for_heart_failure()
    for key, value in changes.items():
        setattr(d.medications[0], key, value)
    return d


def test_a_wrong_dose_number_is_flagged_even_though_the_quote_exists(heart_text):
    from app.verify import verify
    r = verify(heart_draft_with(dose="400 mg"), heart_text)  # the paper says 40 mg
    furosemide = r.medications[0]
    assert furosemide.grounded is True  # the quote is real...
    assert furosemide.needs_confirmation is True  # ...but the number is not
    assert "number 400 in the dose" in furosemide.issues[0]


def test_wrong_frequency_or_duration_numbers_are_flagged_and_right_ones_are_not(heart_text):
    from app.verify import verify
    assert verify(heart_draft_with(frequency="every 8 hours"), heart_text).medications[0].needs_confirmation
    assert verify(heart_draft_with(duration="35 days"), heart_text).medications[0].needs_confirmation
    ok = verify(heart_draft_with(), heart_text).medications[0]
    assert ok.needs_confirmation is False and ok.issues == []


def test_phone_numbers_must_really_be_in_the_document(heart_text):
    from app.verify import verify
    d = draft_for_heart_failure()
    d.follow_ups[0].contact = "555-0142"
    assert verify(d, heart_text).follow_ups[0].needs_confirmation is False
    d.follow_ups[0].contact = "555-9999"
    r = verify(d, heart_text).follow_ups[0]
    assert r.needs_confirmation and "phone number was not found" in r.issues[0]


def test_medicine_names_start_with_a_capital_letter():
    from app.schemas import MedicationDraft
    m = MedicationDraft(name="  naproxen (Aleve)", dose=None, route=None, frequency=None, duration=None, purpose=None,
                        instructions=None, status="stop", source_quote="naproxen (Aleve)")
    assert m.name == "Naproxen (Aleve)"


def test_heart_demo_captures_old_dose_phone_and_the_acetaminophen_limit():
    ex = extract_sample("01_heart_failure.txt")
    lis = next(m for m in ex.medications if m.name == "Lisinopril")
    assert lis.previous_dose == "20 mg" and not lis.needs_confirmation
    assert ex.follow_ups[0].contact == "555-0142 (to schedule)" and not ex.follow_ups[0].needs_confirmation
    cats = {r.category: r.instruction for r in ex.restrictions}
    assert "3,000 mg" in cats["medication_limit"] and "Weigh yourself" in cats["monitoring"]


def test_plan_must_keep_the_old_dose_and_the_phone_number():
    ex = confirm_everything(extract_sample("01_heart_failure.txt"))
    draft = good_draft(ex)
    assert check_plan(draft, ex) == []
    lis_idx = next(n for n, m in enumerate(ex.medications) if m.name == "Lisinopril")
    assert "from 20 mg" in draft.medications[lis_idx].how_to_take and "555-0142 (to schedule)" in draft.follow_ups[0].plain_text
    # the model drops the old dose / the phone number -> caught
    draft.medications[lis_idx].how_to_take = "Take 10 mg once daily."
    draft.follow_ups[0].plain_text = "See the heart doctor within 7 days."
    problems = check_plan(draft, ex)
    assert any(f"med_{lis_idx}" in p and "20" in p for p in problems)
    assert any("fu_0" in p and "contact" in p for p in problems)


def test_the_review_box_can_never_be_skipped():
    ex = confirm_everything(extract_sample("03_hip_replacement.txt"))
    assert any("compared this list" in p for p in readiness_problems(PlanRequest(extraction=ex)))
    assert readiness_problems(PlanRequest(extraction=ex, acknowledged_review=True)) == []


def test_nothing_flagged_still_requires_the_patient_to_confirm_the_review(demo_client=None):
    from app.main import app
    from fastapi.testclient import TestClient
    import os
    os.environ["MEDBRIDGE_DEMO"] = "1"
    try:
        c = TestClient(app)
        text = (SAMPLES / "03_hip_replacement.txt").read_bytes()
        ex = c.post("/extract", files={"file": ("a.txt", text, "text/plain")}).json()
        assert ex["items_needing_confirmation"] == 0  # nothing flagged...
        r = c.post("/plan", json={"extraction": ex})  # ...yet the server still refuses without the review box
        assert r.status_code == 409 and "compared this list" in r.text
        assert c.post("/plan", json={"extraction": ex, "acknowledged_review": True}).status_code == 200
    finally:
        os.environ.pop("MEDBRIDGE_DEMO", None)

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.demo import DemoExtractionClient, DemoPlanClient
from app.extractor import Extractor
from app.main import app
from app.plan import PlanError, PlanGenerator, build_plan_input, check_plan, readiness_problems
from app.schemas import PlanDraft, PlanRequest
from conftest import SAMPLES


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
    assert len(readiness_problems(PlanRequest(extraction=ex))) == 1  # only the unclear-notes tick left
    assert readiness_problems(PlanRequest(extraction=ex, acknowledged_unclear=True)) == []


def test_gate_rejects_empty_plan_and_unknown_language():
    ex = extract_sample("01_heart_failure.txt")
    ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions = [], [], [], []
    assert any("nothing to build" in p for p in readiness_problems(PlanRequest(extraction=ex, acknowledged_unclear=True)))
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
    r = demo_client.post("/plan", json={"extraction": ex, "acknowledged_unclear": True})
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["language"] == "en" and len(plan["medications"]) == 8
    assert any(w["emergency"] for w in plan["warning_signs"])

    # 3) another language
    r = demo_client.post("/plan", json={"extraction": ex, "acknowledged_unclear": True, "language": "es"})
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

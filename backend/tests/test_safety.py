import pytest
from fastapi.testclient import TestClient

from app.demo import DemoExtractionClient, DemoLabelSource
from app.drugs import LocalResolver, LookupUnavailable, RxNormResolver, aliases_from, split_ingredients
from app.extractor import Extractor
from app.main import app
from app.safety import OpenFdaLabelSource, SafetyChecker, _mention
from conftest import SAMPLES


def sample(name):
    text = (SAMPLES / name).read_text(encoding="utf-8")
    ex = Extractor(client=DemoExtractionClient()).extract(text)
    for g in (ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions):
        for i in g:
            i.patient_confirmed = True
    return ex


# ---------- naming ----------
def test_aliases_come_from_brackets_next_to_the_drug():
    assert aliases_from("Tylenol", "Tylenol (acetaminophen) 500 mg - take 2 tablets") == ["acetaminophen"]
    assert aliases_from("Ibuprofen", "Ibuprofen (Advil, Motrin)") == ["Advil", "Motrin"]
    assert aliases_from("X", "X 10 mg (2 tablets)") == []  # brackets with numbers are not names


@pytest.mark.parametrize("name,expected", [
    ("Metoprolol succinate ER", ["metoprolol"]),
    ("Levothyroxine sodium", ["levothyroxine"]),
    ("Amoxicillin-clavulanate", ["amoxicillin", "clavulanate"]),
    ("Oxycodone/acetaminophen", ["oxycodone", "acetaminophen"]),
    ("Potassium chloride", ["potassium chloride"]),  # must not be stripped to nothing
    ("Furosemide 40 mg tablet", ["furosemide"]),
])
def test_split_and_clean_ingredients(name, expected):
    from app.drugs import _clean
    assert split_ingredients(_clean(name)) == expected


def test_local_resolver_knows_brands_and_flags_assumed_names():
    r = LocalResolver()
    assert r.resolve("Percocet", []).ingredients == ["oxycodone", "acetaminophen"]
    assert r.resolve("Percocet", []).source == "local"
    assert r.resolve("Tylenol", ["acetaminophen"]).ingredients == ["acetaminophen"]
    guessed = r.resolve("Zorbitrol", [])
    assert guessed.source == "name" and guessed.ingredients == ["zorbitrol"]  # honest: unverified


# ---------- RxNorm (fixtures follow NIH's documented JSON shapes) ----------
RXCUI = {"idGroup": {"name": "zytonex", "rxnormId": ["202991"]}}
RELATED = {"relatedGroup": {"rxcui": "202991", "conceptGroup": [
    {"tty": "IN", "conceptProperties": [{"rxcui": "4603", "name": "Furosemide", "tty": "IN"}]}]}}


def test_rxnorm_resolves_unknown_brand():
    calls = []

    def fake(url, params):
        calls.append(url)
        return RELATED if "related" in url else RXCUI

    n = RxNormResolver(fake).resolve("Zytonex", [])
    assert n.ingredients == ["furosemide"] and n.source == "rxnorm"
    assert len(calls) == 2


def test_rxnorm_falls_back_to_closest_match_when_exact_name_unknown():
    def fake(url, params):
        if "approximateTerm" in url:
            return {"approximateGroup": {"candidate": [{"rxcui": "202991", "score": "9", "rank": "1"}]}}
        if "related" in url:
            return RELATED
        return {"idGroup": {"name": "zytonxe"}}  # no rxnormId

    assert RxNormResolver(fake).resolve("Zytonxe", []).ingredients == ["furosemide"]


def test_rxnorm_skips_the_network_for_known_brands():
    def boom(url, params):
        raise AssertionError("should not be called")

    assert RxNormResolver(boom).resolve("Lasix", []).ingredients == ["furosemide"]


def test_rxnorm_outage_falls_back_and_stops_calling():
    calls = []

    def down(url, params):
        calls.append(url)
        raise LookupUnavailable("offline")

    r = RxNormResolver(down)
    first, second = r.resolve("Zorbitrol", []), r.resolve("Quindazol", [])
    assert first.source == second.source == "name"
    assert len(calls) == 1  # circuit breaker: one failure, no more waiting on timeouts


# ---------- FDA label source ----------
def test_openfda_parses_and_caches():
    calls = []

    def fake(url, params):
        calls.append(params)
        return {"results": [{"drug_interactions": ["Aspirin may reduce effect.", "Avoid potassium."]}]}

    src = OpenFdaLabelSource(fake)
    assert src.interactions_text("lisinopril") == "Aspirin may reduce effect. Avoid potassium."
    src.interactions_text("lisinopril")
    assert len(calls) == 1 and calls[0]["search"] == 'openfda.generic_name:"lisinopril"'


def test_openfda_no_label_is_none_not_an_error():
    assert OpenFdaLabelSource(lambda u, p: None).interactions_text("nothingium") is None
    assert OpenFdaLabelSource(lambda u, p: {"results": [{}]}).interactions_text("x") is None


# ---------- matching ----------
def test_mention_matches_whole_words_and_brand_names_only():
    text = "NSAIDs may raise bleeding risk. Coumadin levels can change with antibiotics. Ibuprofenic acid is unrelated."
    assert _mention(text, ["warfarin", "coumadin"]) == "Coumadin levels can change with antibiotics."
    assert _mention(text, ["ibuprofen"]) is None  # 'ibuprofenic' is not 'ibuprofen'
    assert _mention(text, ["abc"]) is None  # too short to match safely


def test_mention_truncates_long_sentences():
    long = "Warfarin " + "x " * 300 + "."
    assert len(_mention(long, ["warfarin"])) <= 320


# ---------- the checker on the demo samples ----------
def test_gallbladder_sample_finds_duplicate_conflict_and_interactions():
    report = SafetyChecker(labels=DemoLabelSource()).check(sample("04_gallbladder_surgery.txt"))

    dup = report.duplicates
    assert [d.ingredient for d in dup] == ["acetaminophen"]
    assert set(dup[0].medicines) == {"Tylenol", "Percocet"}

    assert [(c.ingredient, c.stopped, c.still_listed) for c in report.stopped_conflicts] == [("ibuprofen", "Advil", "Motrin IB")]

    pairs = {frozenset((h.drug_a, h.drug_b)) for h in report.interactions}
    assert pairs == {frozenset(("warfarin", "acetaminophen")), frozenset(("warfarin", "ibuprofen"))}
    assert all("Demo sample" in h.source for h in report.interactions)
    assert report.interaction_check == "done"
    assert any("does not mean a combination is safe" in n for n in report.notes)


def test_stopped_medicines_are_not_used_for_interaction_checks():
    # Aspirin is STOPPED in sample 4, and the demo lisinopril text names aspirin: no hint expected.
    report = SafetyChecker(labels=DemoLabelSource()).check(sample("04_gallbladder_surgery.txt"))
    assert not any({"lisinopril", "aspirin"} == {h.drug_a, h.drug_b} for h in report.interactions)


def test_heart_sample_active_aspirin_triggers_the_lisinopril_hint():
    report = SafetyChecker(labels=DemoLabelSource()).check(sample("01_heart_failure.txt"))
    assert [(h.drug_a, h.drug_b) for h in report.interactions] == [("lisinopril", "aspirin")]
    assert not report.duplicates and not report.stopped_conflicts


@pytest.mark.parametrize("name", ["02_pneumonia.txt", "03_hip_replacement.txt"])
def test_clean_samples_have_no_findings(name):
    r = SafetyChecker(labels=DemoLabelSource()).check(sample(name))
    assert not r.duplicates and not r.stopped_conflicts


def test_outage_is_reported_never_treated_as_no_problems():
    class Down:
        source_name = "x"

        def interactions_text(self, ingredient):
            raise LookupUnavailable("offline")

    r = SafetyChecker(labels=Down()).check(sample("04_gallbladder_surgery.txt"))
    assert r.interaction_check == "unavailable" and r.interactions == []
    assert any("NOT checked" in n for n in r.notes)
    assert r.duplicates  # the offline checks still work


def test_without_a_label_source_interactions_are_marked_not_run():
    assert SafetyChecker().check(sample("04_gallbladder_surgery.txt")).interaction_check == "not_run"


# ---------- API ----------
@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setenv("MEDBRIDGE_DEMO", "1")
    return TestClient(app)


def confirmed_body(client, name):
    text = (SAMPLES / name).read_text(encoding="utf-8")
    ex = client.post("/extract", files={"file": ("a.txt", text.encode(), "text/plain")}).json()
    for g in ("medications", "follow_ups", "warning_signs", "restrictions"):
        for i in ex[g]:
            i["patient_confirmed"] = True
    return {"extraction": ex, "acknowledged_unclear": True}


def test_schedule_and_safety_are_gated_like_the_plan(demo):
    text = (SAMPLES / "01_heart_failure.txt").read_text(encoding="utf-8")
    ex = demo.post("/extract", files={"file": ("a.txt", text.encode(), "text/plain")}).json()
    for path in ("/schedule", "/safety", "/plan"):
        assert demo.post(path, json={"extraction": ex}).status_code == 409


def test_schedule_endpoint_on_gallbladder_sample(demo):
    s = demo.post("/schedule", json=confirmed_body(demo, "04_gallbladder_surgery.txt")).json()
    assert [x["time"] for x in s["slots"]] == ["00:00", "06:00", "08:00", "12:00", "18:00", "18:30", "21:30"]
    at_8 = next(x for x in s["slots"] if x["time"] == "08:00")
    assert {i["name"] for i in at_8["items"]} == {"Docusate", "Lisinopril"}
    assert {a["name"] for a in s["as_needed"]} == {"Percocet", "Motrin IB", "Ondansetron"}
    assert s["unscheduled"] == [] and s["tapers"] == []


def test_schedule_endpoint_handles_taper_and_unscheduled(demo):
    s = demo.post("/schedule", json=confirmed_body(demo, "02_pneumonia.txt")).json()
    assert s["tapers"][0]["name"] == "Prednisone" and len(s["tapers"][0]["steps"]) == 2
    h = demo.post("/schedule", json=confirmed_body(demo, "01_heart_failure.txt")).json()
    assert [u["name"] for u in h["unscheduled"]] == ["Aspirin"]  # the paper never gave a frequency


def test_safety_endpoint(demo):
    r = demo.post("/safety", json=confirmed_body(demo, "04_gallbladder_surgery.txt")).json()
    assert r["duplicates"][0]["ingredient"] == "acetaminophen"
    assert r["stopped_conflicts"][0]["still_listed"] == "Motrin IB"


def test_offline_generic_names_do_not_trigger_a_scary_note():
    r = SafetyChecker(labels=DemoLabelSource()).check(sample("04_gallbladder_surgery.txt"))
    assert not any("drug-name database" in n for n in r.notes)


def test_note_appears_when_the_name_lookup_failed_or_found_nothing():
    ex = sample("04_gallbladder_surgery.txt")

    def down(url, params):
        raise LookupUnavailable("offline")

    r = SafetyChecker(resolver=RxNormResolver(down)).check(ex)
    assert any("could not be reached" in n for n in r.notes)

    unknown = lambda url, params: {"idGroup": {"name": "x"}} if "rxcui.json" in url else {"approximateGroup": {"candidate": []}}  # noqa: E731
    r = SafetyChecker(resolver=RxNormResolver(unknown)).check(ex)
    assert any("were not found in the drug-name database" in n and "Ondansetron" in n for n in r.notes)

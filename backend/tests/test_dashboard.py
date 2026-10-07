import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import dashboard, demo_patients
from app.checkins import CheckInEngine
from app.store import Store
from test_patients_api import plan_body


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "d.sqlite3")


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDBRIDGE_DEMO", "1")
    monkeypatch.setenv("MEDBRIDGE_DB", str(tmp_path / "api.sqlite3"))
    monkeypatch.delenv("MEDBRIDGE_TEAM_KEY", raising=False)
    return TestClient(main.app)


def by_name(overview):
    return {r["name"]: r for r in overview["patients"]}


# ---------- the example patients go through the real engine ----------
def test_example_patients_get_the_status_their_story_deserves(store):
    demo_patients.seed(store)
    rows = by_name(dashboard.overview(store))
    assert rows["James Carter"]["status"] == "emergency"
    assert rows["Maria Gonzalez"]["status"] == "call_today"
    assert rows["Robert Singh"]["status"] == "review"
    assert rows["Aisha Khan"]["status"] == "stopped" and rows["Aisha Khan"]["opted_out"]
    assert rows["David Lee"]["status"] == "ok" and rows["Linda Park"]["status"] == "ok"


def test_worst_first_and_stable(store):
    demo_patients.seed(store)
    order = [r["name"] for r in dashboard.overview(store)["patients"]]
    assert order[:4] == ["James Carter", "Maria Gonzalez", "Robert Singh", "Aisha Khan"]
    assert set(order[4:]) == {"David Lee", "Linda Park"}
    assert order[4:] == sorted(order[4:])            # ties are alphabetical, so the list does not jump around


def test_one_message_about_one_warning_sign_is_one_alert(store):
    demo_patients.seed(store)
    james = [a for a in dashboard.overview(store)["open_alerts"] if a["patient_name"] == "James Carter"]
    assert len(james) == 1 and james[0]["level"] == "urgent"
    assert james[0]["title"].startswith("Emergency: ")          # a short heading, not the paper's whole sentence
    assert "chest pain" in james[0]["detail"].lower()


def test_a_handled_alert_keeps_who_and_what_and_feeds_the_response_time(store):
    demo_patients.seed(store)
    o = dashboard.overview(store)
    seen = [a for a in o["seen_alerts"] if a["patient_name"] == "Linda Park"]
    assert len(seen) == 1 and seen[0]["by"] == "N. Rivera, RN" and "photo" in seen[0]["note"]
    assert o["stats"]["median_minutes_to_seen"] == 34
    assert o["stats"]["open_alerts"] == len(o["open_alerts"]) == 3 and o["stats"]["patients"] == 6


def test_silence_is_not_hidden(store):
    demo_patients.seed(store)
    robert = by_name(dashboard.overview(store))["Robert Singh"]
    assert robert["top_alert"] == "Missed medicines two reminders in a row"
    assert robert["adherence"]["rate"] is not None and robert["adherence"]["rate"] < 0.2


def test_weight_trend_and_change(store):
    demo_patients.seed(store)
    w = by_name(dashboard.overview(store))["Maria Gonzalez"]["weight"]
    assert w["latest"] == 177 and w["change"] == 5 and w["trend"] == [172, 172, 174, 177]


def test_seeding_twice_does_not_duplicate_and_reset_leaves_real_patients_alone(store):
    ex = demo_patients.confirmed_extraction("03_hip_replacement.txt")
    real = store.create_patient(name="Real Person", phone=None, mode="simulator", consent=False, language="en", extraction_json=ex.model_dump_json())
    CheckInEngine(store).start(real)
    demo_patients.seed(store)
    demo_patients.seed(store)
    assert len(store.all_patients()) == 7
    assert demo_patients.reset(store) == 6
    left = store.all_patients()
    assert [p["id"] for p in left] == [real] and len(store.messages(real)) == 1
    assert all(not a["patient_id"].startswith("demo-") for a in store.all_alerts())


def test_timestamps_come_from_the_store_clock(store):
    now = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    demo_patients.seed(store, now=now)
    james = [a for a in store.all_alerts() if a["patient_id"] == "demo-james"][0]
    assert datetime.fromisoformat(james["created_at"]) == now - timedelta(minutes=18)


def test_empty_dashboard(store):
    o = dashboard.overview(store)
    assert o["patients"] == [] and o["stats"]["patients"] == 0 and o["stats"]["median_minutes_to_seen"] is None


def test_an_opted_out_patient_with_an_open_alert_is_still_shown_by_the_alert(store):
    demo_patients.seed(store)
    store.update_patient("demo-maria", opted_out=1)
    assert by_name(dashboard.overview(store))["Maria Gonzalez"]["status"] == "call_today"


def test_longest_waiting_first_within_a_status(store):
    ex = demo_patients.confirmed_extraction("03_hip_replacement.txt").model_dump_json()
    times = iter(["2026-01-01T10:00:00+00:00", "2026-01-01T09:00:00+00:00"])
    for name in ("Aaron", "Zed"):
        pid = store.create_patient(name=name, phone=None, mode="simulator", consent=False, language="en", extraction_json=ex)
        store.clock = lambda t=next(times): t
        store.add_alert(pid, "same_day", "x", "y", "r", 0)
    assert [r["name"] for r in dashboard.overview(store)["patients"]] == ["Zed", "Aaron"]   # Zed has waited an hour longer


def test_next_steps_are_fixed_operational_text(store):
    assert "now" in dashboard.next_step("urgent", "universal:chest_pain")
    assert "today" in dashboard.next_step("same_day", "paper0:swelling")
    assert "refill" in dashboard.next_step("same_day", "ran_out").lower()
    assert "another way" in dashboard.next_step("review", "delivery_failed")


def test_headline_falls_back_to_the_title(store):
    assert dashboard.headline("same_day", "weight1", "Weight up 3 lb in 1 day") == "Weight up 3 lb in 1 day"
    assert dashboard.headline("urgent", "universal:chest_pain", "long text") == "Emergency: chest pain"


# ---------- storage ----------
def test_second_acknowledgement_does_not_overwrite_the_first(store):
    ex = demo_patients.confirmed_extraction("03_hip_replacement.txt").model_dump_json()
    pid = store.create_patient(name="A", phone=None, mode="simulator", consent=False, language="en", extraction_json=ex)
    aid = store.add_alert(pid, "review", "t", "d", "r", 0)
    assert store.acknowledge(aid, "first note", "Nurse A") and store.acknowledge(aid, "second note", "Nurse B")
    a = store.alerts(pid)[0]
    assert a["ack_note"] == "first note" and a["ack_by"] == "Nurse A" and a["acknowledged_at"]
    assert store.acknowledge(9999) is False


def test_an_older_database_is_upgraded_without_losing_alerts(tmp_path):
    path = tmp_path / "old.sqlite3"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE alerts (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id TEXT NOT NULL, level TEXT NOT NULL, title TEXT NOT NULL,
          detail TEXT NOT NULL, rule_id TEXT NOT NULL, day INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, acknowledged INTEGER NOT NULL DEFAULT 0);
        INSERT INTO alerts (patient_id, level, title, detail, rule_id, created_at) VALUES ('p', 'urgent', 'old alert', 'd', 'r', '2025-01-01T00:00:00+00:00');
    """)
    conn.commit()
    conn.close()
    store = Store(path)
    assert store.all_alerts()[0]["title"] == "old alert"
    assert store.acknowledge(1, "done", "me") and store.all_alerts()[0]["ack_note"] == "done"


# ---------- the HTTP side ----------
def test_dashboard_endpoints_end_to_end(api):
    assert api.get("/dashboard").json()["patients"] == []
    assert api.post("/demo/patients").json() == {"loaded": 6}
    o = api.get("/dashboard").json()
    assert o["stats"]["emergency"] == 1 and o["patients"][0]["name"] == "James Carter"
    alert = o["open_alerts"][0]
    assert api.post(f"/alerts/{alert['id']}/ack", json={"note": "Called, on the way to ER", "by": "Dr. Shah"}).json() == {"ok": True}
    o = api.get("/dashboard").json()
    assert o["stats"]["emergency"] == 0 and o["seen_alerts"][0]["note"] == "Called, on the way to ER"
    assert api.post("/alerts/999999/ack").status_code == 404
    assert api.delete("/demo/patients").json() == {"removed": 6}
    assert api.get("/dashboard").json()["patients"] == []


def test_acknowledge_still_works_without_a_body(api):
    api.post("/demo/patients")
    aid = api.get("/dashboard").json()["open_alerts"][0]["id"]
    assert api.post(f"/alerts/{aid}/ack").status_code == 200


def test_patient_detail_has_the_plan_and_the_alert_history(api):
    api.post("/demo/patients")
    detail = api.get("/dashboard/patients/demo-maria").json()
    assert detail["patient"]["display_name"] == "Maria Gonzalez"
    assert detail["plan"]["medications"] and detail["plan"]["follow_ups"]
    assert detail["alerts"][0]["next_step"] and detail["weights"][-1]["pounds"] == 177
    assert api.get("/dashboard/patients/nobody").status_code == 404


def test_a_patient_made_on_the_normal_screen_appears_on_the_dashboard(api):
    api.post("/patients", json={"plan": plan_body(api), "name": "Walk In"})
    rows = api.get("/dashboard").json()["patients"]
    assert [r["name"] for r in rows] == ["Walk In"] and rows[0]["status"] == "ok"


def test_without_a_name_the_row_is_still_identifiable(api):
    api.post("/patients", json={"plan": plan_body(api)})
    assert api.get("/dashboard").json()["patients"][0]["name"].startswith("Patient ")


def test_team_access_code(api, monkeypatch):
    assert api.get("/config").json()["team_key_required"] is False
    monkeypatch.setenv("MEDBRIDGE_TEAM_KEY", "s3cret-code")
    assert api.get("/config").json()["team_key_required"] is True
    for call in (lambda h: api.get("/dashboard", headers=h), lambda h: api.get("/dashboard/patients/x", headers=h),
                 lambda h: api.post("/demo/patients", headers=h), lambda h: api.delete("/demo/patients", headers=h),
                 lambda h: api.post("/alerts/1/ack", headers=h)):
        assert call({}).status_code == 401
        assert call({"X-Team-Key": "wrong"}).status_code == 401
        assert call({"X-Team-Key": "sécret".encode()}).status_code == 401      # odd characters are refused, not a server error
    assert api.get("/dashboard", headers={"X-Team-Key": "s3cret-code"}).status_code == 200
    assert api.get("/health").status_code == 200                      # the patient side stays open

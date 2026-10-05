import base64
import hashlib
import hmac

import pytest
from fastapi.testclient import TestClient

import app.main as main
from conftest import SAMPLES

TWILIO_ENV = {"TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "tok", "TWILIO_FROM_NUMBER": "+15559990000",
              "MEDBRIDGE_PUBLIC_URL": "https://medbridge.example"}


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDBRIDGE_DEMO", "1")
    monkeypatch.setenv("MEDBRIDGE_DB", str(tmp_path / "api.sqlite3"))
    for k in TWILIO_ENV:
        monkeypatch.delenv(k, raising=False)
    return TestClient(main.app)


@pytest.fixture
def twilio(api, monkeypatch):
    for k, v in TWILIO_ENV.items():
        monkeypatch.setenv(k, v)
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(main, "build_sender", lambda: (lambda to, body: sent.append((to, body))))
    return sent


def plan_body(api, name="01_heart_failure.txt", review=True):
    text = (SAMPLES / name).read_bytes()
    ex = api.post("/extract", files={"file": ("a.txt", text, "text/plain")}).json()
    ex["medications"] = [m for m in ex["medications"] if m["name"] != "Potassium chloride"]
    for g in ("medications", "follow_ups", "warning_signs", "restrictions"):
        for item in ex[g]:
            item["patient_confirmed"] = True
    return {"extraction": ex, "acknowledged_unclear": True, "acknowledged_review": review}


def create(api, **extra):
    return api.post("/patients", json={"plan": plan_body(api), **extra})


# ---------- simulator ----------
def test_creating_a_patient_needs_the_same_confirmation_as_a_plan(api):
    r = api.post("/patients", json={"plan": plan_body(api, review=False)})
    assert r.status_code == 409 and "compared this list" in r.text


def test_create_advance_reply_and_acknowledge(api):
    state = create(api).json()
    pid = state["patient"]["id"]
    assert state["patient"]["mode"] == "simulator" and len(state["messages"]) == 1
    assert "NOT for emergencies" in state["messages"][0]["body"]
    assert state["next_event"]["label"] == "Day 1, 8:00 AM: Medicine reminder"

    state = api.post(f"/patients/{pid}/advance").json()
    assert state["messages"][-1]["kind"] == "reminder" and state["next_event"]["kind"] == "checkin"

    state = api.post(f"/patients/{pid}/reply", json={"text": "I have chest pain"}).json()
    assert state["messages"][-1]["body"].startswith("This may be an emergency")
    (alert,) = state["alerts"]
    assert alert["level"] == "urgent" and alert["acknowledged"] is False

    assert api.post(f"/alerts/{alert['id']}/ack").json() == {"ok": True}
    assert api.get(f"/patients/{pid}").json()["alerts"][0]["acknowledged"] is True


def test_unknown_patient_and_alert(api):
    assert api.get("/patients/nope").status_code == 404
    assert api.post("/patients/nope/advance").status_code == 404
    assert api.post("/patients/nope/reply", json={"text": "hi"}).status_code == 404
    assert api.post("/alerts/9999/ack").status_code == 404


def test_overlong_replies_are_rejected(api):
    pid = create(api).json()["patient"]["id"]
    assert api.post(f"/patients/{pid}/reply", json={"text": "x" * 1001}).status_code == 422


def test_state_survives_between_requests(api):
    pid = create(api).json()["patient"]["id"]
    api.post(f"/patients/{pid}/advance")
    api.post(f"/patients/{pid}/advance")
    api.post(f"/patients/{pid}/reply", json={"text": "171 and no symptoms"})
    again = api.get(f"/patients/{pid}").json()
    assert again["weights"] == [{"day": 1, "pounds": 171.0}] and len(again["messages"]) >= 5


def test_config_says_whether_real_texts_are_available(api, monkeypatch):
    assert api.get("/config").json()["sms"] is False
    for k, v in TWILIO_ENV.items():
        monkeypatch.setenv(k, v)
    assert api.get("/config").json()["sms"] is True


# ---------- real texts ----------
def test_sms_mode_is_refused_when_twilio_is_not_set_up(api):
    r = create(api, mode="sms", phone="+15551234567", consent_sms=True)
    assert r.status_code == 409 and "not set up" in r.json()["detail"]


def test_sms_mode_needs_a_valid_phone_and_consent(api, twilio):
    assert create(api, mode="sms", phone="12345", consent_sms=True).status_code == 422
    r = create(api, mode="sms", phone="+15551234567", consent_sms=False)
    assert r.status_code == 409 and "agree" in r.json()["detail"]
    assert twilio == []                                               # nothing was sent without consent


def test_sms_mode_sends_the_welcome_text_to_the_normalised_number(api, twilio):
    r = create(api, mode="sms", phone="(555) 123-4567", consent_sms=True)
    assert r.status_code == 200 and r.json()["patient"]["phone_last4"] == "4567"
    assert twilio[0][0] == "+15551234567" and "NOT for emergencies" in twilio[0][1]


# ---------- Twilio webhook ----------
def sign(params, url="https://medbridge.example/sms/incoming", token="tok"):
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_webhook_is_off_until_twilio_and_a_public_url_are_configured(api):
    assert api.post("/sms/incoming", data={"From": "+1555", "Body": "hi"}).status_code == 503


def test_webhook_rejects_unsigned_and_forged_requests(api, twilio):
    form = {"From": "+15551234567", "Body": "hi"}
    assert api.post("/sms/incoming", data=form).status_code == 403
    assert api.post("/sms/incoming", data=form, headers={"X-Twilio-Signature": "forged"}).status_code == 403
    assert api.post("/sms/incoming", data=form, headers={"X-Twilio-Signature": sign(form, token="wrong")}).status_code == 403


def test_webhook_routes_a_signed_reply_to_the_right_patient(api, twilio):
    pid = create(api, mode="sms", phone="+15551234567", consent_sms=True).json()["patient"]["id"]
    api.post(f"/patients/{pid}/advance")                              # the 8:00 reminder goes out
    twilio.clear()
    form = {"From": "+15551234567", "Body": "yes", "MessageSid": "SM1"}
    r = api.post("/sms/incoming", data=form, headers={"X-Twilio-Signature": sign(form)})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/xml") and "<Response>" in r.text
    assert twilio and twilio[0][0] == "+15551234567" and "Marked as taken" in twilio[0][1]
    assert api.get(f"/patients/{pid}").json()["adherence"]["taken"] == 1


def test_webhook_emergency_reply_goes_out_and_raises_an_alert(api, twilio):
    pid = create(api, mode="sms", phone="+15551234567", consent_sms=True).json()["patient"]["id"]
    twilio.clear()
    form = {"From": "+15551234567", "Body": "I have chest pain"}
    api.post("/sms/incoming", data=form, headers={"X-Twilio-Signature": sign(form)})
    assert twilio[0][1].startswith("This may be an emergency")
    assert [a["level"] for a in api.get(f"/patients/{pid}").json()["alerts"]] == ["urgent"]


def test_webhook_from_an_unknown_number_is_ignored_politely(api, twilio):
    form = {"From": "+15550001111", "Body": "hello"}
    r = api.post("/sms/incoming", data=form, headers={"X-Twilio-Signature": sign(form)})
    assert r.status_code == 200 and twilio == []

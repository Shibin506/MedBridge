import base64
import hashlib
import hmac

import httpx
import pytest

from app.sms import SmsError, TwilioSender, normalize_phone, valid_signature
from app.store import Store


# ---------- store ----------
@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "x.sqlite3")
    s.pid = s.create_patient(name="A", phone="+15551234567", mode="sms", consent=True, language="en", extraction_json="{}")
    return s


def test_patient_roundtrip_and_phone_lookup(store):
    p = store.get_patient(store.pid)
    assert p["name"] == "A" and p["consent"] == 1 and p["opted_out"] == 0
    assert store.find_by_phone("+15551234567")["id"] == store.pid
    assert store.find_by_phone("+15550000000") is None and store.get_patient("nope") is None


def test_only_some_fields_can_be_updated(store):
    store.update_patient(store.pid, opted_out=1, sim_day=3)
    assert store.get_patient(store.pid)["sim_day"] == 3
    with pytest.raises(ValueError):
        store.update_patient(store.pid, phone="+1999")


def test_alerts_dedupe_ack_and_sort_by_urgency(store):
    a = store.add_alert(store.pid, "review", "r", "d", "rule1", 0)
    assert store.add_alert(store.pid, "review", "r", "d", "rule1", 0) is None            # same worry, same day
    assert store.add_alert(store.pid, "review", "r", "d", "rule1", 1) is not None         # a new day is a new alert
    store.add_alert(store.pid, "urgent", "u", "d", "rule2", 0)
    assert [x["level"] for x in store.alerts(store.pid)] == ["urgent", "review", "review"]
    assert store.acknowledge(a) is True and store.acknowledge(9999) is False
    assert store.add_alert(store.pid, "review", "r", "d", "rule1", 0) is not None         # acknowledged: may alert again
    assert store.alerts(store.pid)[-1]["acknowledged"] == 1


def test_ongoing_problems_keep_one_open_alert_whatever_the_day(store):
    assert store.add_alert(store.pid, "review", "x", "d", "adherence", 0) is not None
    assert store.add_alert(store.pid, "review", "x", "d", "adherence", 5) is None


def test_weights_upsert_and_adherence_upsert(store):
    store.set_weight(store.pid, 0, 170.0); store.set_weight(store.pid, 0, 171.0); store.set_weight(store.pid, 1, 172.5)
    assert store.weights(store.pid) == {0: 171.0, 1: 172.5}
    store.set_adherence(store.pid, 0, "08:00", "unanswered"); store.set_adherence(store.pid, 0, "08:00", "taken")
    assert store.adherence(store.pid) == [{"day": 0, "slot": "08:00", "status": "taken"}]


def test_data_survives_a_restart(tmp_path):
    path = tmp_path / "keep.sqlite3"
    first = Store(path)
    pid = first.create_patient(name="K", phone=None, mode="simulator", consent=False, language="en", extraction_json="{}")
    first.add_message(pid, "out", "hello", "welcome")
    assert Store(path).messages(pid)[0]["body"] == "hello"


# ---------- phone numbers ----------
@pytest.mark.parametrize("raw,expected", [
    ("+1 (555) 123-4567", "+15551234567"), ("555-123-4567", "+15551234567"), ("+447911123456", "+447911123456"),
    ("12345", None), ("", None), (None, None), ("+0123456789", None), ("call me", None),
])
def test_normalize_phone(raw, expected):
    assert normalize_phone(raw) == expected


# ---------- Twilio sender (against a pretend Twilio) ----------
def sender_with(status, payload=None, record=None):
    def handler(request: httpx.Request):
        if record is not None:
            record.append(request)
        return httpx.Response(status, json=payload or {})
    return TwilioSender("ACtest", "secret-token", "+15559990000", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_twilio_request_shape():
    seen = []
    sender_with(201, {"sid": "SM1"}, seen)("+15551234567", "hello")
    req = seen[0]
    assert req.url.path == "/2010-04-01/Accounts/ACtest/Messages.json" and req.method == "POST"
    assert req.headers["authorization"].startswith("Basic ")
    assert base64.b64decode(req.headers["authorization"].split()[1]) == b"ACtest:secret-token"
    body = req.content.decode()
    assert "To=%2B15551234567" in body and "From=%2B15559990000" in body and "Body=hello" in body


def test_twilio_errors_are_explained_and_never_contain_the_token():
    with pytest.raises(SmsError) as e:
        sender_with(400, {"code": 30034, "message": "unregistered number secret-token"})("+15551234567", "x")
    msg = str(e.value)
    assert "30034" in msg and "registered" in msg and "secret-token" not in msg


def test_twilio_unreachable():
    def boom(request):
        raise httpx.ConnectError("offline")
    s = TwilioSender("AC", "t", "+1555", client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(SmsError, match="Could not reach Twilio"):
        s("+15551234567", "x")


# ---------- webhook signatures ----------
def sign(token, url, params):
    data = url + "".join(k + params[k] for k in sorted(params))
    return base64.b64encode(hmac.new(token.encode(), data.encode(), hashlib.sha1).digest()).decode()


def test_valid_signature_accepts_the_real_one_and_rejects_everything_else():
    params = {"From": "+15551234567", "Body": "yes", "MessageSid": "SM1"}
    good = sign("tok", "https://x.example/sms/incoming", params)
    assert valid_signature("tok", "https://x.example/sms/incoming", params, good)
    assert not valid_signature("other", "https://x.example/sms/incoming", params, good)               # wrong token
    assert not valid_signature("tok", "https://evil.example/sms/incoming", params, good)             # wrong URL
    assert not valid_signature("tok", "https://x.example/sms/incoming", {**params, "Body": "no"}, good)  # tampered body
    assert not valid_signature("tok", "https://x.example/sms/incoming", params, None)
    assert not valid_signature("tok", "https://x.example/sms/incoming", params, "")

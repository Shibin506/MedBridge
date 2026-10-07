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


# ---------- delivery status and plain-English errors ----------
def _sender(handler):
    import httpx
    from app.sms import TwilioSender
    return TwilioSender("ACsid", "secret-token", "+15559990000", client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_send_returns_twilios_message_id():
    import httpx
    s = _sender(lambda req: httpx.Response(201, json={"sid": "SM123", "status": "queued"}))
    assert s.send("+15551230000", "hi") == "SM123"


def test_status_reports_failure_with_the_error_code():
    import httpx
    s = _sender(lambda req: httpx.Response(200, json={"status": "undelivered", "error_code": 30034, "error_message": "Unregistered number"}))
    assert s.status("SM123") == ("undelivered", "30034", "Unregistered number")


def test_status_when_twilio_is_unreachable_is_an_error_not_a_pass():
    import httpx
    import pytest
    from app.sms import SmsError

    def boom(req):
        raise httpx.ConnectError("no network")
    with pytest.raises(SmsError):
        _sender(boom).status("SM123")


def test_unverified_trial_number_gets_a_specific_explanation_and_no_token():
    import httpx
    import pytest
    from app.sms import SmsError
    s = _sender(lambda req: httpx.Response(400, json={"code": 21608, "message": "unverified secret-token"}))
    with pytest.raises(SmsError) as e:
        s.send("+15551230000", "hi")
    text = str(e.value)
    assert "21608" in text and "Verified Caller IDs" in text and "secret-token" not in text


def test_a_stop_reply_at_twilio_level_is_explained():
    from app.sms import explain_error
    assert "START" in explain_error(21610)
    assert "registered" in explain_error("30034")
    assert explain_error("99999", "fallback") == "fallback"


def test_a_text_that_could_not_be_sent_is_marked_not_delivered(tmp_path):
    from app.checkins import CheckInEngine
    from app.demo_patients import confirmed_extraction
    from app.store import Store
    store = Store(tmp_path / "d.sqlite3")
    pid = store.create_patient(name="T", phone="+15551230000", mode="sms", consent=True, language="en",
                               extraction_json=confirmed_extraction("01_heart_failure.txt").model_dump_json())

    def refuse(to, body):
        raise RuntimeError("Twilio error 572006: trial accounts can only use predefined templates")
    CheckInEngine(store, sender=refuse).start(pid)
    msgs = store.messages(pid)
    assert [m["delivery"] for m in msgs] == ["failed"]
    assert "572006" in store.alerts(pid)[0]["detail"]
    CheckInEngine(store, sender=lambda to, body: None).advance(pid)
    assert [m["delivery"] for m in store.messages(pid)] == ["failed", ""]

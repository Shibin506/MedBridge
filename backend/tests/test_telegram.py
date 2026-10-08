from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest
from fastapi.testclient import TestClient

import app.main as main
from app import scheduler, telegram
from app.checkins import CheckInEngine
from app.demo_patients import confirmed_extraction
from app.store import Store
from app.telegram import TelegramClient, TelegramError
from test_patients_api import api, plan_body  # noqa: F401  (api is a fixture)

LA = ZoneInfo("America/Los_Angeles")
TOKEN = "123456789" + ":" + "ABCdefGhIJKlmNoPQRsTUVwxyz012345678"


class FakeTG:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.fail = False
        self.queue: list[dict] = []
        self.offsets: list = []

    def username(self):
        return "MedBridgeBot"

    def send(self, chat_id, text):
        if self.fail:
            raise TelegramError("Telegram error 403: Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text))

    def updates(self, offset, wait_seconds=25):
        self.offsets.append(offset)
        out, self.queue = self.queue, []
        return out


def msg(update_id, chat_id, text, kind="private"):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id, "type": kind}, "text": text}}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "t.sqlite3")


@pytest.fixture
def tg():
    return FakeTG()


def make_engine(tg):
    return lambda s: CheckInEngine(s, telegram=tg.send)


def new_patient(store, token="tok-12345678", when=None, sample="01_heart_failure.txt"):
    if when:
        store.clock = lambda: when.astimezone(timezone.utc).isoformat(timespec="seconds")
    pid = store.create_patient(name="Tele", phone=None, mode="telegram", consent=False, language="en",
                               extraction_json=confirmed_extraction(sample).model_dump_json(), timezone="America/Los_Angeles", link_token=token)
    store.clock = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    return pid


# ---------- the client ----------
def client(handler):
    return TelegramClient(TOKEN, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_send_posts_plain_text_to_the_right_chat():
    seen = {}

    def handler(req):
        seen["url"], seen["json"] = str(req.url), req.read()
        return httpx.Response(200, json={"ok": True, "result": {}})
    client(handler).send("42", "hello")
    assert seen["url"].endswith("/sendMessage") and b'"chat_id":"42"' in seen["json"].replace(b" ", b"") and b"parse_mode" not in seen["json"]


def test_a_long_message_is_cut_to_telegrams_limit():
    seen = {}
    client(lambda req: seen.update(body=req.read()) or httpx.Response(200, json={"ok": True, "result": {}})).send("1", "x" * 9000)
    assert len(seen["body"]) < 4300


def test_errors_are_plain_and_never_contain_the_token():
    blocked = client(lambda r: httpx.Response(403, json={"ok": False, "error_code": 403, "description": f"Forbidden: bot was blocked {TOKEN}"}))
    with pytest.raises(TelegramError) as e:
        blocked.send("1", "hi")
    assert "blocked" in str(e.value) and TOKEN not in str(e.value)
    with pytest.raises(TelegramError, match="rejected the bot token"):
        client(lambda r: httpx.Response(401, json={"ok": False, "description": "Unauthorized"})).me()
    with pytest.raises(TelegramError, match="Another copy"):
        client(lambda r: httpx.Response(409, json={"ok": False, "description": "Conflict"})).updates(None, 1)

    def boom(r):
        raise httpx.ConnectError("no network " + TOKEN)
    with pytest.raises(TelegramError) as e2:
        client(boom).send("1", "hi")
    assert TOKEN not in str(e2.value)


def test_username_is_looked_up_once():
    calls = []
    c = client(lambda r: calls.append(1) or httpx.Response(200, json={"ok": True, "result": {"username": "MedBridgeBot"}}))
    assert c.username() == "MedBridgeBot" and c.username() == "MedBridgeBot" and len(calls) == 1


def test_updates_asks_only_for_messages_after_the_saved_position():
    seen = {}
    c = client(lambda r: seen.update(body=r.read()) or httpx.Response(200, json={"ok": True, "result": [{"update_id": 5}]}))
    assert c.updates(7, 1) == [{"update_id": 5}]
    assert b'"offset":7' in seen["body"].replace(b" ", b"") and b"allowed_updates" in seen["body"]


# ---------- reading messages ----------
def test_only_private_text_messages_count():
    assert telegram.parse_update(msg(1, 42, " hi ")) == ("42", "hi")
    assert telegram.parse_update(msg(1, -100, "hi", kind="group")) is None
    assert telegram.parse_update({"update_id": 1, "message": {"chat": {"id": 1, "type": "private"}, "photo": []}}) is None
    assert telegram.parse_update({"update_id": 1, "edited_message": {}}) is None


def test_start_link_secret_parsing():
    assert telegram.start_token("/start abc12345") == "abc12345"
    assert telegram.start_token("/start@MedBridgeBot abc_12-45") == "abc_12-45"
    for bad in ("/start", "/start short", "/start has space here", "start abc12345", "/start abc12345 extra"):
        assert telegram.start_token(bad) is None


# ---------- connecting a patient ----------
def test_pressing_start_connects_the_patient_and_sends_the_welcome(store, tg):
    pid = new_patient(store)
    tg.queue = [msg(10, 555, "/start tok-12345678")]
    assert telegram.poll_once(store, make_engine(tg), tg) == 1
    p = store.get_patient(pid)
    assert p["chat_id"] == "555" and p["consent"] == 1 and p["link_token"] == "" and p["linked_at"]
    assert len(tg.sent) == 1 and tg.sent[0][0] == "555" and "NOT for emergencies" in tg.sent[0][1]
    assert store.get_kv("telegram_offset") == "11"


def test_a_link_works_once(store, tg):
    new_patient(store)
    tg.queue = [msg(10, 555, "/start tok-12345678"), msg(11, 777, "/start tok-12345678")]
    telegram.poll_once(store, make_engine(tg), tg)
    assert [c for c, _ in tg.sent] == ["555", "777"] and "already used" in tg.sent[1][1]
    assert store.find_by_chat("777") is None


def test_strangers_are_told_how_to_connect_and_groups_are_ignored(store, tg):
    tg.queue = [msg(1, 900, "hello"), msg(2, -5, "hello", kind="group")]
    telegram.poll_once(store, make_engine(tg), tg)
    assert len(tg.sent) == 1 and tg.sent[0][0] == "900" and "open the link" in tg.sent[0][1]


def test_replies_are_understood_like_text_messages(store, tg):
    pid = new_patient(store)
    tg.queue = [msg(1, 555, "/start tok-12345678")]
    telegram.poll_once(store, make_engine(tg), tg)
    CheckInEngine(store, telegram=tg.send).advance(pid)               # the 8:00 reminder
    tg.queue = [msg(2, 555, "yes")]
    telegram.poll_once(store, make_engine(tg), tg)
    assert [a["status"] for a in store.adherence(pid)] == ["taken"]
    tg.queue = [msg(3, 555, "I have chest pain")]
    telegram.poll_once(store, make_engine(tg), tg)
    assert any(a["level"] == "urgent" for a in store.alerts(pid)) and "Call 911" in tg.sent[-1][1]


def test_stop_in_telegram_stops_the_messages(store, tg):
    pid = new_patient(store)
    tg.queue = [msg(1, 555, "/start tok-12345678"), msg(2, 555, "/stop")]
    telegram.poll_once(store, make_engine(tg), tg)
    assert store.get_patient(pid)["opted_out"] == 1
    sent_before = len(tg.sent)
    assert scheduler.tick(store, make_engine(tg), datetime.now(timezone.utc) + timedelta(days=2)) == 0
    assert len(tg.sent) == sent_before


def test_one_bad_message_does_not_block_the_queue(store, tg):
    tg.queue = [msg(1, 900, "hi"), msg(2, 901, "hi")]

    def flaky(s):
        raise RuntimeError("boom")
    telegram.poll_once(store, flaky, tg)
    assert store.get_kv("telegram_offset") == "3"                     # moved past both, not stuck on the first


def test_a_message_telegram_refuses_is_marked_not_delivered_and_alerts(store, tg):
    pid = new_patient(store)
    store.link_telegram(pid, "555")
    tg.fail = True
    CheckInEngine(store, telegram=tg.send).start(pid)
    assert [m["delivery"] for m in store.messages(pid)] == ["failed"]
    assert store.alerts(pid)[0]["rule_id"] == "delivery_failed" and "blocked" in store.alerts(pid)[0]["detail"]


# ---------- timer ----------
def test_unconnected_patients_get_nothing_and_connected_ones_start_from_pressing_start(store, tg):
    pid = new_patient(store, when=datetime(2026, 3, 1, 9, 0, tzinfo=LA))
    assert scheduler.tick(store, make_engine(tg), datetime(2026, 3, 2, 8, 1, tzinfo=LA)) == 0 and tg.sent == []   # never pressed Start
    store.clock = lambda: datetime(2026, 3, 2, 7, 0, tzinfo=LA).astimezone(timezone.utc).isoformat(timespec="seconds")
    store.link_telegram(pid, "555")                                      # pressed Start at 07:00 on Mar 2
    assert scheduler.tick(store, make_engine(tg), datetime(2026, 3, 2, 8, 1, tzinfo=LA)) == 1        # 08:00 today: yes
    assert store.alerts(pid) == []                                       # yesterday's reminders were before they connected: not "missed"
    assert "time for your medicines" in tg.sent[0][1]


# ---------- the web API ----------
def test_creating_a_telegram_patient_needs_telegram_to_be_set_up(api, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert api.get("/config").json()["telegram"] is False
    r = api.post("/patients", json={"plan": plan_body(api), "mode": "telegram"})
    assert r.status_code == 409 and "Telegram is not set up" in r.text


def test_the_connect_link_and_the_unconnected_state(api, monkeypatch, tg):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "get_telegram", lambda: tg)
    assert api.get("/config").json()["telegram"] is True
    state = api.post("/patients", json={"plan": plan_body(api), "mode": "telegram", "name": "Tess"}).json()
    link = state["telegram"]["link_url"]
    assert link.startswith("https://t.me/MedBridgeBot?start=") and len(link.split("=")[1]) >= 12
    assert state["telegram"]["linked"] is False and state["messages"] == [] and state["scheduled_next"] is None
    pid = state["patient"]["id"]
    assert api.post(f"/patients/{pid}/advance").status_code == 409        # nothing can be sent before they press Start
    # the patient presses Start
    store = Store()
    telegram.handle_update(store, CheckInEngine(store, telegram=tg.send), tg, msg(1, 321, "/start " + link.split("=")[1]))
    state = api.get(f"/patients/{pid}").json()
    assert state["telegram"] == {"linked": True, "link_url": None, "problem": None} and len(state["messages"]) == 1
    assert state["scheduled_next"]["label"]
    assert api.get("/dashboard").json()["patients"][0]["mode"] == "telegram"


def test_the_bot_name_failing_to_load_is_reported_not_crashed(api, monkeypatch):
    class Down(FakeTG):
        def username(self):
            raise TelegramError("Could not reach Telegram (ConnectError).")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "get_telegram", lambda: Down())
    state = api.post("/patients", json={"plan": plan_body(api), "mode": "telegram"}).json()
    assert state["telegram"]["link_url"] is None and "Could not reach Telegram" in state["telegram"]["problem"]


def test_a_bot_token_shaped_string_is_caught_by_the_secret_check():
    from test_repo_hygiene import KEY_SHAPES
    assert KEY_SHAPES.search(f"TELEGRAM_BOT_TOKEN={TOKEN}")


def test_the_dashboard_shows_who_never_connected_and_never_leaks_the_link(api, monkeypatch, tg):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setattr(main, "get_telegram", lambda: tg)
    state = api.post("/patients", json={"plan": plan_body(api), "mode": "telegram", "name": "Tess"}).json()
    secret = state["telegram"]["link_url"].split("=")[1]
    row = api.get("/dashboard").json()["patients"][0]
    assert row["connected"] is False and row["mode"] == "telegram"
    detail = api.get(f"/dashboard/patients/{state['patient']['id']}")
    assert detail.json()["telegram"] == {"linked": False} and secret not in detail.text
    assert secret not in api.get("/dashboard").text

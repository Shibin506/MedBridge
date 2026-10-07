from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app import scheduler
from app.checkins import CheckInEngine
from app.demo_patients import confirmed_extraction
from app.store import Store

LA = ZoneInfo("America/Los_Angeles")
CHI = ZoneInfo("America/Chicago")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "s.sqlite3")


@pytest.fixture
def sent():
    return []


def engine_factory(sent):
    return lambda s: CheckInEngine(s, sender=lambda to, body: sent.append((to, body)))


def enroll(store, when, *, tz="America/Los_Angeles", sample="01_heart_failure.txt", mode="sms", consent=True, phone="+15551230000"):
    """A patient who signed up at `when` (a timezone-aware time). Heart-failure timeline: 08:00 reminder, 09:00 check-in, 21:30 reminder."""
    store.clock = lambda: when.astimezone(timezone.utc).isoformat(timespec="seconds")
    pid = store.create_patient(name="T", phone=phone, mode=mode, consent=consent, language="en",
                               extraction_json=confirmed_extraction(sample).model_dump_json(), timezone=tz)
    store.clock = lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    return pid


def run(store, sent, now):
    return scheduler.tick(store, engine_factory(sent), now)


def bodies(sent):
    return [b for _, b in sent]


def test_a_reminder_goes_out_at_the_patients_local_time(store, sent):
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    assert run(store, sent, datetime(2026, 3, 2, 7, 59, tzinfo=LA)) == 0
    assert run(store, sent, datetime(2026, 3, 2, 8, 0, 30, tzinfo=LA)) == 1
    assert sent[0][0] == "+15551230000" and "time for your medicines" in sent[0][1] and "8:00 AM" in sent[0][1]


def test_the_same_text_is_never_sent_twice(store, sent):
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    t = datetime(2026, 3, 2, 8, 1, tzinfo=LA)
    assert run(store, sent, t) == 1
    assert run(store, sent, t + timedelta(seconds=30)) == 0 and run(store, sent, t + timedelta(minutes=5)) == 0
    assert len(sent) == 1


def test_signing_up_in_the_afternoon_does_not_send_this_morning(store, sent):
    enroll(store, datetime(2026, 3, 1, 15, 0, tzinfo=LA))
    assert run(store, sent, datetime(2026, 3, 1, 15, 1, tzinfo=LA)) == 0       # 08:00 and 09:00 are in the past
    assert run(store, sent, datetime(2026, 3, 1, 21, 31, tzinfo=LA)) == 1      # the evening reminder is still to come
    assert "9:30 PM" in sent[0][1]
    assert store.alerts(store.all_patients()[0]["id"]) == []                    # nothing was "missed"


def test_the_whole_day_in_order_with_the_morning_check_in(store, sent):
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    for hh, mm in ((8, 1), (9, 1), (21, 31)):
        run(store, sent, datetime(2026, 3, 2, hh, mm, tzinfo=LA))
    assert [("medicines" in b, "Quick check-in" in b) for b in bodies(sent)] == [(True, False), (False, True), (True, False)]


def test_days_count_from_signing_up(store, sent):
    pid = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    run(store, sent, datetime(2026, 3, 2, 8, 1, tzinfo=LA))
    run(store, sent, datetime(2026, 3, 3, 8, 1, tzinfo=LA))
    labels = [m["sim_label"] for m in store.messages(pid) if m["direction"] == "out"]
    assert labels == ["Day 2, 8:00 AM", "Day 3, 8:00 AM"]


def test_each_patients_own_time_zone_decides(store, sent):
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), tz="America/Los_Angeles", phone="+15550000001")
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), tz="America/Chicago", phone="+15550000002")
    now = datetime(2026, 3, 2, 8, 1, tzinfo=CHI)                 # 6:01 AM in Los Angeles
    run(store, sent, now)
    assert [to for to, _ in sent] == ["+15550000002"]            # only Chicago's 8:00 has arrived
    run(store, sent, datetime(2026, 3, 2, 8, 1, tzinfo=LA))
    # Los Angeles now gets its 8:00; Chicago (already at 10:01 on its clock) also gets its 9:00 check-in
    assert sorted(to for to, _ in sent) == ["+15550000001", "+15550000002", "+15550000002"]


def test_a_late_text_is_skipped_and_the_care_team_is_told(store, sent):
    pid = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    assert run(store, sent, datetime(2026, 3, 2, 10, 45, tzinfo=LA)) == 0     # server was off: 08:00 is 165 min late, 09:00 is 105 min late
    assert sent == []
    alerts = store.alerts(pid)
    assert len(alerts) == 1 and alerts[0]["level"] == "review" and "not sent" in alerts[0]["title"]
    assert run(store, sent, datetime(2026, 3, 2, 10, 46, tzinfo=LA)) == 0     # and it is not retried


def test_grace_period_boundary(store, sent):
    pid = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    # 09:29 -> the 08:00 text is 89 minutes late (still sent) and the 09:00 check-in is 29 minutes late (sent)
    assert run(store, sent, datetime(2026, 3, 2, 9, 29, tzinfo=LA)) == 2
    assert store.alerts(pid) == []


def test_just_past_the_grace_period_it_is_skipped(store, sent):
    pid = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    assert run(store, sent, datetime(2026, 3, 2, 9, 31, tzinfo=LA)) == 1      # 08:00 is 91 minutes late: skipped; 09:00 check-in is sent
    assert "Quick check-in" in sent[0][1]
    assert [a["rule_id"] for a in store.alerts(pid)] == ["schedule_missed"]


def test_patients_who_said_stop_or_never_agreed_get_nothing(store, sent):
    stopped = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), phone="+15550000001")
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), consent=False, phone="+15550000002")
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), mode="simulator", phone=None)
    store.update_patient(stopped, opted_out=1)
    assert run(store, sent, datetime(2026, 3, 2, 8, 1, tzinfo=LA)) == 0 and sent == []


def test_one_broken_patient_does_not_stop_the_others(store, sent):
    bad = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), phone="+15550000001")
    enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), phone="+15550000002")
    conn = store._conn()
    with conn:
        conn.execute("UPDATE patients SET extraction = 'not json' WHERE id = ?", (bad,))
    conn.close()
    run(store, sent, datetime(2026, 3, 2, 8, 1, tzinfo=LA))
    assert [to for to, _ in sent] == ["+15550000002"]


def test_a_failed_send_raises_an_alert_but_is_not_repeated(store):
    pid = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))

    def boom(to, body):
        raise RuntimeError("Twilio down")
    make = lambda s: CheckInEngine(s, sender=boom)  # noqa: E731
    t = datetime(2026, 3, 2, 8, 1, tzinfo=LA)
    assert scheduler.tick(store, make, t) == 1
    assert scheduler.tick(store, make, t + timedelta(minutes=1)) == 0
    assert [a["rule_id"] for a in store.alerts(pid)] == ["delivery_failed"]


def test_unanswered_scheduled_reminders_raise_the_missed_medicine_alert(store, sent):
    pid = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA), sample="03_hip_replacement.txt")
    for hh in (6, 8, 9, 14):                                   # the patient never replies
        run(store, sent, datetime(2026, 3, 2, hh, 1, tzinfo=LA))
    assert any(a["rule_id"] == "adherence" for a in store.alerts(pid))


def test_the_patients_reply_to_a_scheduled_reminder_is_understood(store, sent):
    pid = enroll(store, datetime(2026, 3, 1, 23, 0, tzinfo=LA))
    run(store, sent, datetime(2026, 3, 2, 8, 1, tzinfo=LA))
    engine = CheckInEngine(store)
    engine.reply(pid, "yes")
    assert [a["status"] for a in store.adherence(pid)] == ["taken"]


def test_next_due_and_its_label(store):
    pid = enroll(store, datetime(2026, 3, 1, 20, 0, tzinfo=LA))
    p = store.get_patient(pid)
    at, label = scheduler.next_due(p, datetime(2026, 3, 1, 20, 5, tzinfo=LA))
    assert label == "Sun 9:30 PM" and at == datetime(2026, 3, 1, 21, 30, tzinfo=LA)
    at, label = scheduler.next_due(p, datetime(2026, 3, 1, 22, 0, tzinfo=LA))
    assert label == "Mon 8:00 AM"


def test_a_bad_time_zone_name_falls_back(monkeypatch):
    monkeypatch.delenv("MEDBRIDGE_TZ", raising=False)
    assert scheduler.resolve_timezone("Europe/Paris") == "Europe/Paris"
    assert scheduler.resolve_timezone("Not/AZone") == scheduler.FALLBACK_TZ
    assert scheduler.resolve_timezone("") == scheduler.FALLBACK_TZ
    assert scheduler.resolve_timezone("../../etc/passwd") == scheduler.FALLBACK_TZ
    monkeypatch.setenv("MEDBRIDGE_TZ", "America/Chicago")
    assert scheduler.resolve_timezone("nonsense") == "America/Chicago"


def test_the_clock_change_does_not_shift_the_reminder(store, sent):
    # US clocks go forward on 2026-03-08: 8:00 AM stays 8:00 AM on the wall clock.
    enroll(store, datetime(2026, 3, 7, 23, 0, tzinfo=LA))
    assert run(store, sent, datetime(2026, 3, 8, 7, 59, tzinfo=LA)) == 0
    assert run(store, sent, datetime(2026, 3, 8, 8, 1, tzinfo=LA)) == 1


def test_the_scheduler_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("MEDBRIDGE_SCHEDULER", "off")
    assert scheduler.enabled() is False
    monkeypatch.delenv("MEDBRIDGE_SCHEDULER")
    assert scheduler.enabled() is True

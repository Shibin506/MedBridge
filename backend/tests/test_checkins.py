import json

import pytest

from app import checkins
from app.checkins import CheckInEngine, checkin_plan, clock, timeline
from app.demo import DemoExtractionClient
from app.extractor import Extractor
from app.store import Store
from conftest import SAMPLES


def extraction(name="01_heart_failure.txt", drop=("Potassium chloride",)):
    ex = Extractor(client=DemoExtractionClient()).extract((SAMPLES / name).read_text(encoding="utf-8"))
    ex.medications = [m for m in ex.medications if m.name not in drop]
    for g in (ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions):
        for i in g:
            i.patient_confirmed = True
    return ex


class Bot:
    """A tiny test driver: one patient, one engine, a list of texts that 'went out to a phone'."""

    def __init__(self, tmp_path, name="01_heart_failure.txt", mode="simulator", phone=None, sender_fails=False):
        self.sent: list[tuple[str, str]] = []

        def sender(to, body):
            if sender_fails:
                raise RuntimeError("Twilio error 30034: unregistered number")
            self.sent.append((to, body))

        self.store = Store(tmp_path / "t.sqlite3")
        self.engine = CheckInEngine(self.store, sender=sender)
        self.ex = extraction(name)
        self.pid = self.store.create_patient(name="Pat", phone=phone, mode=mode, consent=True, language="en",
                                             extraction_json=self.ex.model_dump_json())

    def advance(self, n=1):
        for _ in range(n):
            self.engine.advance(self.pid)
        return self.last_out()

    def say(self, text):
        before = len(self.store.messages(self.pid))
        self.engine.reply(self.pid, text)
        return [m["body"] for m in self.store.messages(self.pid)[before:] if m["direction"] == "out"]

    def last_out(self):
        return [m for m in self.store.messages(self.pid) if m["direction"] == "out"][-1]["body"]

    def alerts(self):
        return self.store.alerts(self.pid)

    def levels(self):
        return sorted(a["level"] for a in self.alerts())


@pytest.fixture
def bot(tmp_path):
    return Bot(tmp_path)


# ---------- the daily timeline ----------
def test_timeline_has_reminders_in_order_then_a_checkin_after_the_morning_reminder():
    events = timeline(extraction())
    assert [(e.kind, e.time) for e in events] == [("reminder", "08:00"), ("checkin", "09:00"), ("reminder", "21:30")]


def test_overnight_doses_are_never_texted():
    ex = extraction("04_gallbladder_surgery.txt")   # Tylenol every 6 hours includes midnight
    assert all(e.time != "00:00" for e in timeline(ex))


def test_checkin_questions_come_from_the_patients_own_paper():
    plan = checkin_plan(extraction())
    assert plan.weight is True and "swelling" in plan.labels and "dizziness" in plan.labels
    hip = checkin_plan(extraction("03_hip_replacement.txt"))
    assert hip.weight is False and hip.enabled                      # symptoms only: no weighing on that paper


def test_clock_labels():
    assert [clock(t) for t in ("00:00", "08:00", "12:30", "21:30")] == ["12:00 AM", "8:00 AM", "12:30 PM", "9:30 PM"]


# ---------- the first message ----------
def test_welcome_says_not_for_emergencies_and_how_to_stop(bot):
    bot.engine.start(bot.pid)
    text = bot.last_out()
    assert "NOT for emergencies" in text and "911" in text and "STOP" in text


# ---------- reminders ----------
def test_a_reminder_lists_the_medicines_and_asks_yes_or_no(bot):
    msg = bot.advance()
    assert "8:00 AM" in msg and "Furosemide 40 mg" in msg and "Metoprolol" in msg and "Reply YES" in msg
    assert "Atorvastatin" not in msg                                  # that one is bedtime


def test_yes_marks_taken_and_no_marks_missed(bot):
    bot.advance()
    assert bot.say("yes")[0].startswith("Thank you! Marked as taken")
    bot.advance(2)                                                    # check-in, then the 9:30 PM reminder
    assert "Okay, I noted" in bot.say("no")[0]
    status = {a["slot"]: a["status"] for a in bot.store.adherence(bot.pid)}
    assert status == {"08:00": "taken", "21:30": "missed"}


def test_running_out_of_medicine_alerts_the_care_team(bot):
    bot.advance()
    reply = bot.say("no, I ran out of my pills")[0]
    assert "refill" in reply
    assert [a["title"] for a in bot.alerts() if a["level"] == "same_day"] == ["Patient says they ran out of medicine"]


def test_an_unanswered_reminder_is_recorded_and_two_in_a_row_alert_once(bot):
    bot.advance(4)       # 8:00 (unanswered) -> 9:00 check-in -> 9:30 PM (unanswered) -> next day 8:00
    bot.advance(2)
    statuses = [a["status"] for a in bot.store.adherence(bot.pid)]
    assert statuses.count("unanswered") >= 2
    alerts = [a for a in bot.alerts() if a["rule_id"] == "adherence"]
    assert len(alerts) == 1 and alerts[0]["level"] == "review"        # one open alert, not one per day


def test_a_late_yes_after_the_next_text_arrived_still_counts(bot):
    bot.advance(2)                                                    # 8:00 reminder, then the 9:00 check-in arrives
    assert bot.say("yes")[0].startswith("Thank you! Marked as taken")
    assert {a["slot"]: a["status"] for a in bot.store.adherence(bot.pid)}["08:00"] == "taken"


# ---------- the morning check-in ----------
def test_checkin_asks_for_weight_and_the_papers_symptoms(bot):
    msg = bot.advance(2)
    assert "weight" in msg and "swelling" in msg and "chest pain" in msg and "NONE" in msg


def test_weight_and_all_clear_is_recorded_with_a_warm_reply(bot):
    bot.advance(2)
    reply = bot.say("172 and no symptoms")[0]
    assert "recorded 172 lb" in reply and "Glad you feel fine" in reply
    assert bot.store.weights(bot.pid) == {0: 172.0}
    assert bot.alerts() == []


def test_missing_weight_is_asked_for_again_without_losing_the_context(bot):
    bot.advance(2)
    assert "Please send today's weight" in bot.say("none")[0]
    assert "recorded 171 lb" in bot.say("171")[0]


def test_weight_gain_over_the_papers_number_raises_a_same_day_alert(bot):
    bot.advance(2); bot.say("170")
    bot.advance(3)                                                    # 9:30 PM, then day 2: 8:00 and the 9:00 check-in
    reply = bot.say("174.5")[0]                                       # +4.5 lb in a day; the paper says more than 3
    assert "Weight up 4.5 lb in 1 day" in reply and "Call your doctor" in reply and "555-0142" in reply
    assert [a["level"] for a in bot.alerts() if a["rule_id"].startswith("weight")] == ["same_day"]


def test_a_normal_weight_change_raises_nothing(bot):
    bot.advance(2); bot.say("170")
    bot.advance(3)
    bot.say("172")
    assert [a for a in bot.alerts() if a["rule_id"].startswith("weight")] == []


def test_symptoms_from_the_paper_alert_with_the_papers_own_action(bot):
    bot.advance(2)
    reply = bot.say("171 but my ankles are very swollen")[0]
    assert "More swelling in your feet, ankles or belly: Call your doctor" in reply
    assert any(a["level"] == "same_day" and "swelling" in a["title"].lower() for a in bot.alerts())


def test_negated_symptoms_do_not_alert(bot):
    bot.advance(2)
    reply = bot.say("171, no swelling and no dizziness")[0]
    assert bot.alerts() == [] and "recorded 171 lb" in reply


# ---------- emergencies ----------
def test_chest_pain_is_an_emergency_reply_and_an_urgent_alert(bot):
    bot.advance(2)
    reply = bot.say("I have chest pain")[0]
    assert reply.startswith("This may be an emergency. Call 911 now") and "Do not wait for a text reply" in reply
    assert bot.levels() == ["urgent"]                                 # one alert, not a paper rule plus a duplicate


def test_an_emergency_is_recognised_at_any_time_even_during_a_reminder(bot):
    bot.advance()
    assert bot.say("I just fainted")[0].startswith("This may be an emergency")
    assert bot.levels() == ["urgent"]


def test_thoughts_of_self_harm_get_the_crisis_line(bot):
    bot.advance(2)
    reply = bot.say("I want to kill myself")[0]
    assert "988" in reply and "911" in reply and bot.levels() == ["urgent"]


def test_mild_breathing_trouble_is_same_day_with_a_911_instruction(bot):
    bot.advance(2)
    reply = bot.say("171 and a bit short of breath")[0]
    assert "call 911" in reply.lower() and "Call your doctor" in reply
    assert "urgent" not in bot.levels()


def test_severe_breathing_trouble_is_an_emergency(bot):
    bot.advance(2)
    assert bot.say("I can't breathe")[0].startswith("This may be an emergency")


# ---------- uncertainty goes to a person, never to reassurance ----------
def test_a_vague_worry_creates_a_review_alert_and_no_reassurance(bot):
    bot.advance(2)
    reply = bot.say("I feel really bad today")[0]
    assert "asked your care team to read your message" in reply and "Good to hear" not in reply
    assert bot.levels() == ["review"]


def test_gibberish_gets_a_helpful_prompt_but_no_alert(bot):
    bot.advance(2)
    assert "Please send today's weight" in bot.say("banana")[0]      # the check-in is still waiting for a weight
    assert bot.alerts() == []
    bot.advance(1)                                                    # a reminder arrives instead
    assert "did not understand" in bot.say("banana")[0]
    assert bot.alerts() == []


def test_a_blood_sugar_number_is_not_saved_as_a_weight(bot):
    bot.advance()
    bot.say("my blood sugar is 150")
    assert bot.store.weights(bot.pid) == {}


def test_a_weight_with_a_unit_is_accepted_outside_the_checkin(bot):
    bot.advance()
    assert "recorded 172 lb" in bot.say("weight 172 lbs")[0]
    assert bot.store.weights(bot.pid) == {0: 172.0}


# ---------- STOP / START / HELP ----------
def test_stop_ends_all_texts_and_start_turns_them_back_on(bot):
    bot.advance()
    assert "no more texts" in bot.say("STOP")[0].lower()
    count = len(bot.store.messages(bot.pid))
    bot.advance()
    assert len(bot.store.messages(bot.pid)) == count                  # nothing is sent while opted out
    assert bot.say("it hurts") == []                                  # and it does not answer (a person may still read it)
    assert "Welcome back" in bot.say("start")[0]
    bot.advance()
    assert len(bot.store.messages(bot.pid)) > count


def test_help_explains_and_mentions_911(bot):
    assert "911" in bot.say("HELP")[0]


# ---------- real phones ----------
def test_sms_mode_delivers_every_outgoing_text_to_the_phone(tmp_path):
    b = Bot(tmp_path, mode="sms", phone="+15551234567")
    b.engine.start(b.pid)
    b.advance()
    b.say("yes")
    assert [to for to, _ in b.sent] == ["+15551234567"] * 3
    assert "NOT for emergencies" in b.sent[0][1]


def test_simulator_mode_never_calls_the_sender(tmp_path):
    b = Bot(tmp_path, mode="simulator")
    b.engine.start(b.pid); b.advance()
    assert b.sent == []


def test_a_text_that_cannot_be_delivered_becomes_a_care_team_alert(tmp_path):
    b = Bot(tmp_path, mode="sms", phone="+15551234567", sender_fails=True)
    b.engine.start(b.pid); b.advance()
    alerts = [a for a in b.alerts() if a["rule_id"] == "delivery_failed"]
    assert len(alerts) == 1 and "30034" in alerts[0]["detail"]        # one open alert, however many texts failed


def test_messages_carry_the_simulated_time(bot):
    bot.advance(2)
    labels = [m["sim_label"] for m in bot.store.messages(bot.pid)]
    assert labels == ["Day 1, 8:00 AM", "Day 1, 9:00 AM"]


def test_state_has_everything_the_screens_need(bot):
    bot.engine.start(bot.pid); bot.advance(2); bot.say("172 and no symptoms")
    s = bot.engine.state(bot.pid)
    assert s["patient"]["day"] == 1 and s["weights"] == [{"day": 1, "pounds": 172.0}]
    assert s["next_event"]["label"] == "Day 1, 9:30 PM: Medicine reminder"
    assert s["checkin_asks_weight"] is True and s["weight_rules"] == ["3 lb in 1 day", "5 lb in 7 days"]
    assert {r["action"] for r in s["alert_rules"]} == {"Call your doctor", "Call 911"}
    assert json.dumps(s)                                              # it must be JSON-serialisable for the API

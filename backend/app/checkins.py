"""Daily text check-ins: reminders for the schedule, a morning check-in, and what to do with each reply.

All decisions are made by code (see redflags.py). The wording of every reply is a fixed template.
Texting is never an emergency channel: every first message says so, and an emergency reply says "call 911" first.
"""

import re
from dataclasses import dataclass
from typing import Any, Callable

from . import redflags as rf
from .schedule import build_schedule
from .schemas import ExtractionResult, ScheduleSlot
from .store import Store

CHECKIN_TIME = "09:00"
WELCOME = ("Hi, this is MedBridge. I will text you reminders for your discharge plan and check in each morning. "
           "I am a helper, not a doctor, and texting is NOT for emergencies: if you think you are in danger, call 911. "
           "Reply STOP to stop texts, HELP for help.")
HELP = ("MedBridge sends reminders about your discharge plan. Reply YES or NO to a medicine reminder. In the morning, send your weight "
        "and tell us about any symptoms. Reply STOP to stop. If you think it is an emergency, call 911.")
STOPPED = ("OK, no more texts from MedBridge. Reply START to turn them back on. If you need help, call your care team; "
           "in an emergency, call 911.")
STARTED = "Welcome back. I will text you again. If you think it is an emergency, call 911."
URGENT_REPLY = ("This may be an emergency. Call 911 now, or have someone take you to the nearest emergency room. "
                "Do not wait for a text reply. I have also told your care team.")
SELF_HARM_REPLY = (" If you are thinking about hurting yourself, call or text 988 (in the US) or call 911 right now.")
UNKNOWN_REPLY = ("Sorry, I did not understand. For a medicine reminder reply YES or NO. In the morning send your weight and any "
                 "symptoms. If you feel unwell, call your doctor. In an emergency, call 911.")
REVIEW_REPLY = ("Thank you for telling me. I have asked your care team to read your message. If it gets worse or you think it is an "
                "emergency, call 911; otherwise call your doctor today.")


@dataclass
class Event:
    kind: str                       # reminder | checkin
    time: str                       # "08:00"
    slot: ScheduleSlot | None = None


def clock(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    return f"{h % 12 or 12}:{m:02d} {'AM' if h < 12 else 'PM'}"


@dataclass
class CheckinPlan:
    weight: bool
    labels: list[str]               # symptoms to ask about, in the patient's own plan

    @property
    def enabled(self) -> bool:
        return self.weight or bool(self.labels)


def checkin_plan(ex: ExtractionResult) -> CheckinPlan:
    weight = any("weigh" in r.instruction.lower() for r in ex.restrictions)
    labels: list[str] = []
    for rule in rf.rules_from_paper(ex):
        if rule.concept and rule.concept not in rf.UNIVERSAL_URGENT:
            label = rf.BY_ID[rule.concept].label
            if label not in labels:
                labels.append(label)
    return CheckinPlan(weight=weight, labels=labels[:4])


def timeline(ex: ExtractionResult) -> list[Event]:
    events = [Event("reminder", s.time, s) for s in build_schedule(ex.medications).slots if s.label != "Overnight"]
    if checkin_plan(ex).enabled:
        events.append(Event("checkin", CHECKIN_TIME))
    return sorted(events, key=lambda e: (e.time, e.kind != "reminder"))


def clinic_line(ex: ExtractionResult) -> str:
    for f in ex.follow_ups:
        if f.contact:
            phone = re.search(r"\+?\d[\d\s().-]{5,}\d", f.contact)
            return f" The number on your paper: {phone.group(0).strip() if phone else f.contact} ({f.what})."
    return ""


class CheckInEngine:
    def __init__(self, store: Store, sender: Callable[[str, str], None] | None = None):
        self.store = store
        self.sender = sender  # delivers a text to a real phone (None for the on-screen simulator)

    # ---- helpers -----------------------------------------------------------------
    def _patient(self, pid: str) -> dict[str, Any]:
        p = self.store.get_patient(pid)
        if p is None:
            raise KeyError(pid)
        return p

    @staticmethod
    def extraction(p: dict[str, Any]) -> ExtractionResult:
        return ExtractionResult.model_validate_json(p["extraction"])

    def _label(self, p: dict[str, Any], time: str | None = None) -> str:
        return f"Day {p['sim_day'] + 1}" + (f", {clock(time)}" if time else "")

    def _send(self, p: dict[str, Any], body: str, kind: str, time: str | None = None) -> None:
        self.store.add_message(p["id"], "out", body, kind, self._label(p, time))
        if self.sender and p["mode"] == "sms" and p["phone"] and not p["opted_out"]:
            try:
                self.sender(p["phone"], body)
            except Exception as exc:  # a text that never arrived must not disappear silently
                self.store.add_alert(p["id"], rf.REVIEW, "A text message could not be delivered", str(exc)[:240],
                                     "delivery_failed", p["sim_day"])

    # ---- sending -------------------------------------------------------------------
    def start(self, pid: str) -> None:
        p = self._patient(pid)
        self._send(p, WELCOME, "welcome")

    def advance(self, pid: str) -> None:
        """Send the next reminder or check-in. (In the simulator this is how time moves forward.)"""
        p = self._patient(pid)
        if p["opted_out"]:
            return
        ex = self.extraction(p)
        events = timeline(ex)
        if not events:
            return
        day, cursor = p["sim_day"], p["sim_cursor"]

        awaiting = p["awaiting"]
        if awaiting.startswith("reminder:"):                      # the last reminder was never answered
            self.store.set_adherence(pid, day, awaiting.split(":", 1)[1], "unanswered")
            self._adherence_alert(p, ex)
        if cursor >= len(events):
            day, cursor = day + 1, 0
        ev = events[cursor]
        p = {**p, "sim_day": day}
        if ev.kind == "reminder":
            body = self._reminder_text(ev)
            awaiting_next = f"reminder:{ev.time}"
        else:
            body = self._checkin_text(ex)
            awaiting_next = "checkin"
        self.store.update_patient(pid, sim_day=day, sim_cursor=cursor + 1, awaiting=awaiting_next)
        self._send(p, body, ev.kind, ev.time)

    @staticmethod
    def _reminder_text(ev: Event) -> str:
        lines = []
        for item in ev.slot.items:  # type: ignore[union-attr]
            extra = f" ({item.note})" if item.note else ""
            lines.append(f"- {item.name} {item.dose or ''}{extra}".replace("  ", " ").strip())
        return (f"It is {clock(ev.time)}: time for your medicines.\n" + "\n".join(lines) +
                "\nReply YES when you have taken them, or NO if you could not.")

    @staticmethod
    def _checkin_text(ex: ExtractionResult) -> str:
        plan = checkin_plan(ex)
        parts = ["Good morning! Quick check-in."]
        if plan.weight:
            parts.append("1) What is your weight today, in pounds? (After using the bathroom, before eating.)")
        symptoms = ", ".join(plan.labels + ["chest pain"])
        parts.append(f"{'2) ' if plan.weight else ''}Any of these today: {symptoms}? Reply NONE if you feel fine, or tell me what you notice.")
        if plan.weight:
            parts.append("Example: 172 and no symptoms")
        return "\n".join(parts)

    def _adherence_alert(self, p: dict[str, Any], ex: ExtractionResult) -> None:
        """Two medicine reminders in a row that were not confirmed as taken -> ask the care team to check in."""
        history = sorted(self.store.adherence(p["id"]), key=lambda a: (a["day"], a["slot"]))
        if len(history) >= 2 and all(a["status"] != "taken" for a in history[-2:]):
            self.store.add_alert(p["id"], rf.REVIEW, "Missed medicines two reminders in a row",
                                 "The last two medicine reminders were not confirmed as taken. Consider calling to check in.",
                                 "adherence", p["sim_day"])

    def _late_answer(self, p: dict[str, Any], text: str) -> str | None:
        """'yes'/'no' sent after the next text already arrived still answers the most recent unanswered reminder."""
        history = sorted(self.store.adherence(p["id"]), key=lambda a: (a["day"], a["slot"]))
        if not history or history[-1]["status"] != "unanswered" or p["sim_day"] - history[-1]["day"] > 1:
            return None
        last = history[-1]
        if rf.says_no(text):
            self.store.set_adherence(p["id"], last["day"], last["slot"], "missed")
            return "Okay, I noted that you did not take them. If something makes it hard to take a medicine, please tell your care team."
        if rf.says_yes(text):
            self.store.set_adherence(p["id"], last["day"], last["slot"], "taken")
            return "Thank you! Marked as taken."
        return None

    def _record_weight(self, p: dict[str, Any], ex: ExtractionResult, text: str, *, force: bool) -> tuple[str, list[rf.Flag]] | None:
        """Save a weight from a reply. In the morning check-in any number counts; at other times the message must say it is a weight."""
        if not checkin_plan(ex).weight or not (force or rf.looks_like_weight(text)):
            return None
        pounds = rf.parse_weight(text)
        if pounds is None:
            return None
        day = p["sim_day"]
        history = {d: w for d, w in self.store.weights(p["id"]).items() if d < day}
        self.store.set_weight(p["id"], day, pounds)
        return f"Thanks, I recorded {pounds:g} lb.", rf.check_weight(rf.weight_rules(ex), history, day, pounds)

    # ---- replies ---------------------------------------------------------------------
    def reply(self, pid: str, text: str) -> None:
        p = self._patient(pid)
        text = text.strip()
        if not text:
            return
        self.store.add_message(pid, "in", text, "reply", self._label(p))
        word = re.sub(r"[^a-z]", "", text.lower())
        if word in {"stop", "stopall", "unsubscribe", "cancel", "end", "quit"}:
            self.store.update_patient(pid, opted_out=1)
            return self._reply(p, STOPPED, "system")
        if word == "start":
            self.store.update_patient(pid, opted_out=0)
            return self._reply({**p, "opted_out": 0}, STARTED, "system")
        if word in {"help", "info"}:
            return self._reply(p, HELP, "system")
        if p["opted_out"]:
            return

        ex = self.extraction(p)
        day, awaiting = p["sim_day"], p["awaiting"]
        flags: list[rf.Flag] = []
        notes: list[str] = []
        handled = False
        keep_waiting = False

        if awaiting.startswith("reminder:"):
            slot = awaiting.split(":", 1)[1]
            if rf.says_no(text):
                self.store.set_adherence(pid, day, slot, "missed")
                handled = True
                if rf.ran_out(text):
                    flags.append(rf.Flag(rf.SAME_DAY, "ran_out", "Patient says they ran out of medicine",
                                         f"Patient wrote: “{text[:200]}”. Needs a refill or a call.", "Call your doctor"))
                    notes.append("Thank you for telling me. I have asked your care team about a refill.")
                else:
                    notes.append("Okay, I noted that you did not take them. If something makes it hard to take a medicine, "
                                 "please tell your care team.")
                self._adherence_alert(p, ex)
            elif rf.says_yes(text):
                self.store.set_adherence(pid, day, slot, "taken")
                handled = True
                notes.append("Thank you! Marked as taken.")
            if handled:
                self.store.update_patient(pid, awaiting="")
        elif awaiting == "checkin" and (late := self._late_answer(p, text)) and rf.parse_weight(text) is None:
            notes.append(late)
            handled = True
        elif awaiting == "checkin":
            plan = checkin_plan(ex)
            saved = self._record_weight(p, ex, text, force=True)
            if saved:
                notes.append(saved[0])
                flags += saved[1]
                handled = True
            elif (plan.weight and day not in self.store.weights(pid) and not rf.evaluate_message(text, rf.rules_from_paper(ex))
                  and not rf.sounds_concerning(text)):
                keep_waiting = True
                notes.append("Please send today's weight in pounds, for example 172.")
            if rf.says_all_clear(text) or handled:
                handled = True
            # the check-in stays open until today's weight is in (when the plan asks for one), so a later "171" still counts
            if not plan.weight or day in self.store.weights(pid):
                self.store.update_patient(pid, awaiting="")

        if not handled and awaiting != "checkin":                   # a weight sent at some other time
            saved = self._record_weight(p, ex, text, force=False)
            if saved:
                notes.append(saved[0])
                flags += saved[1]
                handled = True

        message_flags = rf.evaluate_message(text, rf.rules_from_paper(ex))
        flags += message_flags
        if not flags and not handled and not keep_waiting and rf.sounds_concerning(text):
            flags.append(rf.Flag(rf.REVIEW, "review", "Message needs a person to read it",
                                 f"Patient wrote: “{text[:200]}”. No rule matched, so a person should read it.", ""))

        raised: set[tuple[str, str]] = set()
        for f in flags:                                           # one message about one warning sign is one alert, not one per word in it
            if (f.level, f.title) not in raised:
                raised.add((f.level, f.title))
                self.store.add_alert(pid, f.level, f.title, f.detail, f.rule_id, day)
        self._reply(p, self._compose(ex, flags, notes, handled, text), "reply")

    def _reply(self, p: dict[str, Any], body: str, kind: str) -> None:
        self._send(p, body, kind)

    def _compose(self, ex: ExtractionResult, flags: list[rf.Flag], notes: list[str], handled: bool, text: str) -> str:
        urgent = [f for f in flags if f.level == rf.URGENT]
        same_day = [f for f in flags if f.level == rf.SAME_DAY]
        if urgent:
            extra = SELF_HARM_REPLY if any("suicidal" in f.rule_id for f in urgent) else ""
            return URGENT_REPLY + extra
        from_paper = [f for f in same_day if f.rule_id.startswith(("paper", "weight"))]
        if same_day and not from_paper:                       # e.g. "I ran out of medicine": answered by the note, not by the paper
            return " ".join(notes) + clinic_line(ex)
        same_day = from_paper
        if same_day:
            seen: set[str] = set()
            lines = []
            for f in sorted(same_day, key=lambda f: f.clarify_911):          # a clear match beats a "downgraded" one
                concept = f.rule_id.split(":")[-1]
                if concept not in seen and len(lines) < 4:
                    seen.add(concept)
                    lines.append(f"- {f.short or f.title}: {f.action or 'Call your doctor'}")
            tail = " If it becomes severe, or you cannot catch your breath, call 911." if any(f.clarify_911 for f in same_day) else ""
            return ("Thank you for telling me. Your discharge paper says:\n" + "\n".join(lines) +
                    "\nPlease call your doctor today. I have told your care team." + clinic_line(ex) + tail)
        if any(f.level == rf.REVIEW for f in flags):
            return REVIEW_REPLY
        if notes:
            tail = " Glad you feel fine. Your care team is here if that changes." if rf.says_all_clear(text) and not notes[-1].startswith("Please send") else ""
            return " ".join(notes) + tail
        if handled or rf.says_all_clear(text):
            return "Good to hear. Keep following your plan, and tell me if anything changes."
        return UNKNOWN_REPLY

    # ---- everything the screens need -----------------------------------------------------
    def state(self, pid: str) -> dict[str, Any]:
        p = self._patient(pid)
        ex = self.extraction(p)
        events = timeline(ex)
        cursor, day = p["sim_cursor"], p["sim_day"]
        nxt = None
        if events:
            ev = events[cursor] if cursor < len(events) else events[0]
            nd = day if cursor < len(events) else day + 1
            what = ("Medicine reminder" if ev.kind == "reminder" else "Morning check-in")
            nxt = {"day": nd + 1, "time": clock(ev.time), "kind": ev.kind, "label": f"Day {nd + 1}, {clock(ev.time)}: {what}"}
        adherence = self.store.adherence(pid)
        weights = self.store.weights(pid)
        return {
            "patient": {"id": p["id"], "name": p["name"], "mode": p["mode"], "opted_out": bool(p["opted_out"]),
                        "phone_last4": (p["phone"] or "")[-4:], "day": day + 1},
            "messages": self.store.messages(pid),
            "alerts": [{**a, "acknowledged": bool(a["acknowledged"])} for a in self.store.alerts(pid)],
            "weights": [{"day": d + 1, "pounds": w} for d, w in sorted(weights.items())],
            "adherence": {s: sum(a["status"] == s for a in adherence) for s in ("taken", "missed", "unanswered")},
            "next_event": nxt,
            "alert_rules": [{"sign": s.symptom, "action": s.action, "level": rf.URGENT if "911" in s.action else rf.SAME_DAY}
                            for s in ex.warning_signs if rf.is_call_action(s.action)],
            "weight_rules": [f"{r.pounds:g} lb in {'1 day' if r.days == 1 else f'{r.days} days'}" for r in rf.weight_rules(ex)],
            "checkin_asks_weight": checkin_plan(ex).weight,
        }

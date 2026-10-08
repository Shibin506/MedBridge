"""Sends reminders and check-ins on time, in the patient's own time zone (real texts only; the phone simulator is stepped by hand).

How it works, in plain words:
  * Every patient has a timeline for one day (the 8:00 reminder, the 12:00 reminder, the 9:00 check-in...), built from their confirmed plan.
  * Every 30 seconds ``tick`` looks at each real-message patient (SMS or a linked Telegram chat): which of today's texts are due now and not yet sent?
  * "Not yet sent" is remembered in the database (``last_event``), so a restart never repeats a text.
  * Only texts that became due AFTER the patient signed up are sent (signing up at 3 PM does not fire the 8 AM reminder).
  * A text that is more than GRACE_MINUTES late (the server was off) is NOT sent: a "take your medicine" text hours late can mislead.
    It is skipped and the care team gets a "please read" alert, so a missed reminder is never silent.

Marking a text as handled happens BEFORE sending it: if something crashes in between, a patient may miss one text (the care team is not
told) rather than get the same text twice every 30 seconds. See the "Reminder timer" part of docs/phase-4.md.
"""

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import redflags as rf
from .checkins import CheckInEngine, clock, timeline
from .store import Store

log = logging.getLogger("uvicorn.error")

GRACE_MINUTES = 90
LOOKBACK_DAYS = 2           # never look further back than this, whatever the database says
TICK_SECONDS = 30
FALLBACK_TZ = "America/Los_Angeles"


def default_timezone() -> str:
    return os.environ.get("MEDBRIDGE_TZ") or FALLBACK_TZ


def resolve_timezone(name: str | None) -> str:
    """A valid IANA zone name ("America/Chicago"), else the server's default. Never raises."""
    for candidate in (name, default_timezone(), "UTC"):
        if candidate:
            try:
                ZoneInfo(candidate)
                return candidate
            except (ZoneInfoNotFoundError, ValueError, OSError):
                continue
    return "UTC"


def _zone(name: str) -> tzinfo:
    try:
        return ZoneInfo(name or default_timezone())
    except (ZoneInfoNotFoundError, ValueError, OSError):
        return timezone.utc


@dataclass(frozen=True)
class Due:
    day: int            # 0 = the day the patient signed up
    index: int          # position in that day's timeline
    key: str            # "2026-10-07#03": sorts in time order
    at: datetime        # the moment it is due, in the patient's time zone
    late: bool          # True = too late to send


def _parse(iso: str) -> datetime:
    t = datetime.fromisoformat(iso)
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _at(d: date, hhmm: str, tz: tzinfo) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, time(h, m), tzinfo=tz)


def due_events(p: dict[str, Any], now: datetime) -> list[Due]:
    """Texts that are due now for this patient and have not been handled yet, oldest first."""
    ex = CheckInEngine.extraction(p)
    events = timeline(ex)
    tz = _zone(p["timezone"])
    enrolled = _parse(p["linked_at"] or p["created_at"]).astimezone(tz)      # Telegram patients start when they press Start
    today = now.astimezone(tz).date()
    first = max(enrolled.date(), today - timedelta(days=LOOKBACK_DAYS))
    out: list[Due] = []
    d = first
    while d <= today:
        for idx, ev in enumerate(events):
            at = _at(d, ev.time, tz)
            key = f"{d.isoformat()}#{idx:02d}"
            if at <= enrolled or at > now or key <= (p["last_event"] or ""):
                continue
            out.append(Due(day=(d - enrolled.date()).days, index=idx, key=key, at=at, late=now - at > timedelta(minutes=GRACE_MINUTES)))
        d += timedelta(days=1)
    return out


def next_due(p: dict[str, Any], now: datetime) -> tuple[datetime, str] | None:
    """The next text that will be sent, with a friendly label: "Wed 8:00 AM"."""
    ex = CheckInEngine.extraction(p)
    events = timeline(ex)
    if not events:
        return None
    tz = _zone(p["timezone"])
    enrolled = _parse(p["linked_at"] or p["created_at"]).astimezone(tz)
    start = now.astimezone(tz)
    d = max(enrolled.date(), start.date())
    for _ in range(3):
        for idx, ev in enumerate(events):
            at = _at(d, ev.time, tz)
            if at > start and at > enrolled and f"{d.isoformat()}#{idx:02d}" > (p["last_event"] or ""):
                return at, f"{at.strftime('%a')} {clock(ev.time)}"
        d += timedelta(days=1)
    return None


def tick(store: Store, make_engine: Callable[[Store], CheckInEngine], now: datetime | None = None) -> int:
    """One pass over every real-text patient. Returns how many texts were sent."""
    now = now or datetime.now(timezone.utc)
    sent = 0
    for p in store.all_patients():
        reachable = (p["mode"] == "sms" and p["consent"]) or (p["mode"] == "telegram" and p["chat_id"])
        if not reachable or p["opted_out"]:
            continue
        try:
            engine = make_engine(store)
            for due in due_events(p, now):
                store.update_patient(p["id"], last_event=due.key)          # handled first: never send the same text twice
                if due.late:
                    log.warning("Scheduled text %s for patient %s was %d min late: not sent", due.key, p["id"], (now - due.at).total_seconds() // 60)
                    store.add_alert(p["id"], rf.REVIEW, "A scheduled text was not sent",
                                    f"A reminder due at {due.at.strftime('%a %I:%M %p').lstrip('0')} could not be sent on time (the server may have been off), "
                                    "so it was skipped instead of arriving late. Consider calling to check in.", "schedule_missed", due.day)
                    continue
                engine.send_event(p["id"], due.day, due.index)
                sent += 1
        except Exception:                                                 # one patient's problem must not stop everyone else's texts
            log.exception("Scheduler could not process patient %s", p["id"])
    return sent


def enabled() -> bool:
    return os.environ.get("MEDBRIDGE_SCHEDULER", "on").lower() not in {"off", "0", "false", "no"}

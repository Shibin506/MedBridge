"""Fictional example patients for the care-team dashboard, so a demo (or a first look) is not an empty page.

Each patient lives out a few scripted days through the REAL check-in engine: the same reminders, the same rules,
the same alerts a real patient would cause. Nothing here is written straight into the alert table.
Every id starts with "demo-", so removing them never touches anyone else. All names are made up.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .checkins import CheckInEngine, timeline
from .demo import DemoExtractionClient
from .extractor import Extractor
from .schemas import ExtractionResult
from .store import Store

DEMO_PREFIX = "demo-"
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
FAKE_MEDICINE = "Potassium chloride"   # the made-up medicine in the demo heart-failure paper (the patient would remove it on the confirm screen)
STEP_MINUTES = 75                      # time between scripted actions, so the messages look spread over a day or two


@dataclass
class Day:
    """What the patient does on one day. `meds`: 'yes' / 'no' / None (no answer) for every reminder. `checkin`: their reply.
    `events`: stop after this many of the day's texts; `until_checkin`: the scenario ends right after the check-in reply
    (the day is still in progress)."""
    meds: str | None = "yes"
    checkin: str | None = "None, I feel fine"
    events: int | None = None
    until_checkin: bool = False


@dataclass
class Scenario:
    pid: str
    name: str
    sample: str
    days: list[Day]
    minutes_ago: int                                   # when the last scripted action happened
    seen: list[tuple[str, str, str, int]] = field(default_factory=list)   # (alert title contains, note, by, minutes after the alert)


SCENARIOS = [
    Scenario("demo-maria", "Maria Gonzalez", "01_heart_failure.txt", [
        Day(checkin="172 and no symptoms"), Day(checkin="172"), Day(checkin="174 and no symptoms"),
        Day(checkin="177 and my ankles are swollen", until_checkin=True),
    ], minutes_ago=95),
    Scenario("demo-james", "James Carter", "02_pneumonia.txt", [
        Day(), Day(checkin="I have chest pain and trouble breathing", until_checkin=True),
    ], minutes_ago=18),
    Scenario("demo-linda", "Linda Park", "03_hip_replacement.txt", [
        Day(), Day(), Day(checkin="I notice some drainage at my incision"), Day(),
    ], minutes_ago=300, seen=[("drainage", "Called at 2:10 PM. Patient is sending a photo to the surgeon's office. Dressing kept dry; follow-up call tomorrow.",
                               "N. Rivera, RN", 34)]),
    Scenario("demo-robert", "Robert Singh", "04_gallbladder_surgery.txt", [
        Day(meds="yes", checkin=None, events=1), Day(meds=None, checkin=None), Day(meds=None, checkin=None),
    ], minutes_ago=380),
    Scenario("demo-aisha", "Aisha Khan", "02_pneumonia.txt", [
        Day(), Day(meds="yes", checkin="STOP"),
    ], minutes_ago=1500),
    Scenario("demo-david", "David Lee", "01_heart_failure.txt", [
        Day(checkin="168 and no symptoms"), Day(checkin="168"), Day(checkin="167 and feeling good"),
    ], minutes_ago=210),
]


def confirmed_extraction(sample: str) -> ExtractionResult:
    """The sample paper after the patient has checked every line (what the confirm screen produces)."""
    text = (SAMPLES_DIR / sample).read_text(encoding="utf-8")
    ex = Extractor(client=DemoExtractionClient()).extract(text)
    ex.medications = [m for m in ex.medications if m.name != FAKE_MEDICINE]
    for group in (ex.medications, ex.follow_ups, ex.warning_signs, ex.restrictions):
        for item in group:
            item.patient_confirmed = True
    return ex


def _actions(ex: ExtractionResult, days: list[Day]) -> list[tuple[str, str]]:
    """Turns the scripted days into ('advance', '') and ('reply', text) steps, following this patient's own timeline."""
    events = timeline(ex)
    steps: list[tuple[str, str]] = []
    for day in days:
        for n, ev in enumerate(events):
            if day.events is not None and n >= day.events:
                break
            steps.append(("advance", ""))
            answer = day.meds if ev.kind == "reminder" else day.checkin
            if answer:
                steps.append(("reply", answer))
            if day.until_checkin and ev.kind == "checkin":
                break
    return steps


def seed(store: Store, now: datetime | None = None) -> list[str]:
    """Replaces any earlier example patients with fresh ones. Returns their ids."""
    store.delete_patients(DEMO_PREFIX)
    now = now or datetime.now(timezone.utc)
    original_clock = store.clock
    try:
        for sc in SCENARIOS:
            ex = confirmed_extraction(sc.sample)
            steps = _actions(ex, sc.days)
            end = now - timedelta(minutes=sc.minutes_ago)
            times = [end - timedelta(minutes=STEP_MINUTES * (len(steps) - 1 - i)) for i in range(len(steps))]
            stamp = {"t": times[0] if times else end}
            store.clock = lambda: stamp["t"].isoformat(timespec="seconds")
            store.create_patient(name=sc.name, phone=None, mode="simulator", consent=False, language="en",
                                 extraction_json=ex.model_dump_json(), pid=sc.pid)
            engine = CheckInEngine(store)
            engine.start(sc.pid)
            for (kind, text), when in zip(steps, times):
                stamp["t"] = when
                engine.advance(sc.pid) if kind == "advance" else engine.reply(sc.pid, text)
            for needle, note, by, minutes in sc.seen:
                alert = next((a for a in store.alerts(sc.pid) if needle in a["title"].lower() or needle in a["detail"].lower()), None)
                if alert:
                    stamp["t"] = datetime.fromisoformat(alert["created_at"]) + timedelta(minutes=minutes)
                    store.acknowledge(alert["id"], note, by)
    finally:
        store.clock = original_clock
    return [sc.pid for sc in SCENARIOS]


def reset(store: Store) -> int:
    return store.delete_patients(DEMO_PREFIX)

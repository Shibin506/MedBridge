import pytest

from app.schedule import build_schedule
from app.schemas import Medication


def med(name="Testol", dose="10 mg", frequency=None, instructions=None, duration=None, status="new", quote="Testol 10 mg"):
    return Medication(name=name, dose=dose, route="oral", frequency=frequency, duration=duration, purpose=None,
                      instructions=instructions, status=status, source_quote=quote, grounded=True,
                      needs_confirmation=False)


def times(freq, instructions=None):
    sched = build_schedule([med(frequency=freq, instructions=instructions)])
    return [s.time for s in sched.slots], sched


@pytest.mark.parametrize("freq,expected", [
    ("once daily", ["08:00"]),
    ("every morning", ["08:00"]),
    ("1 tablet at bedtime", ["21:30"]),
    ("once daily in the evening", ["18:30"]),
    ("twice daily", ["08:00", "20:00"]),
    ("twice a day with meals", ["08:00", "18:30"]),
    ("three times daily", ["08:00", "14:00", "20:00"]),
    ("three times a day with meals", ["08:00", "12:30", "18:30"]),
    ("four times daily", ["08:00", "12:00", "16:00", "20:00"]),
    ("every 12 hours", ["08:00", "20:00"]),
    ("every 8 hours", ["06:00", "14:00", "22:00"]),
    ("every 6 hours", ["00:00", "06:00", "12:00", "18:00"]),
    ("every 24 hours", ["08:00"]),
])
def test_regular_patterns(freq, expected):
    assert times(freq)[0] == expected


def test_instructions_can_set_the_time_of_day():
    assert times("daily", "take in the morning with food")[0] == ["08:00"]
    assert times("once daily", "take at bedtime")[0] == ["21:30"]


@pytest.mark.parametrize("freq", [
    "every 4-6 hours only if wheezing", "as needed for pain", "PRN",
    "every 6 hours ONLY IF pain is severe", "every 8 hours with food if you have swelling",
])
def test_as_needed_is_never_given_a_clock_time(freq):
    t, sched = times(freq)
    assert t == [] and len(sched.as_needed) == 1


@pytest.mark.parametrize("freq,why", [
    ("every 4-6 hours", "range"),
    ("every 5 hours", "5 hours"),
    ("once a week", "specific days"),
    ("every 3 days", "specific days"),
    ("whenever you remember", "could not understand"),
])
def test_unknown_patterns_are_not_guessed(freq, why):
    t, sched = times(freq)
    assert t == [] and not sched.as_needed
    assert why in sched.unscheduled[0].reason


def test_missing_frequency_is_unscheduled():
    sched = build_schedule([med(frequency=None)])
    assert sched.unscheduled[0].reason == "Your paper does not say how often to take this."


def test_stop_medicines_are_not_scheduled():
    sched = build_schedule([med(frequency="once daily", status="stop")])
    assert not sched.slots and not sched.unscheduled and not sched.as_needed


def test_slots_are_grouped_sorted_and_carry_notes():
    meds = [
        med("B", "5 mg", "twice daily", instructions="take with food"),
        med("A", "1 mg", "every morning", status="changed", duration="7 days"),
        med("C", "2 mg", "at bedtime"),
    ]
    sched = build_schedule(meds)
    # "twice daily ... take with food" -> breakfast and dinner
    assert [s.time for s in sched.slots] == ["08:00", "18:30", "21:30"]
    morning = sched.slots[0]
    assert morning.label == "Morning" and [i.name for i in morning.items] == ["B", "A"]
    a = morning.items[1]
    assert "for 7 days" in a.note and "dose changed" in a.note


def test_taper_is_recognised_from_dose_text_or_source_quote():
    quote = "Prednisone taper: 40 mg daily for 2 days, then 20 mg daily for 2 days, then stop."
    sched = build_schedule([med("Prednisone", "40 mg for 2 days, then 20 mg for 2 days", "daily", quote=quote)])
    assert not sched.slots
    t = sched.tapers[0]
    assert [(s.when, s.dose) for s in t.steps] == [("Days 1-2", "40 mg"), ("Days 3-4", "20 mg")]
    assert t.after == "Then stop."

    # Same taper found only in the quote, with a useless dose field
    sched = build_schedule([med("Prednisone", "varies", "daily", quote=quote)])
    assert len(sched.tapers) == 1


def test_single_course_is_not_mistaken_for_a_taper():
    quote = "Apixaban 2.5 mg - 1 tablet by mouth twice daily for 35 days after surgery."
    sched = build_schedule([med("Apixaban", "2.5 mg", "twice daily", duration="35 days", quote=quote)])
    assert not sched.tapers and len(sched.slots) == 2

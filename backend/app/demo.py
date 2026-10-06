"""Demo mode (MEDBRIDGE_DEMO=1): the whole app works with NO API key.

Two tiny fake "LLM clients" that look like ``anthropic.Anthropic()`` to our code but answer from
canned data. They exist for (1) developing the UI, (2) a hackathon fallback if Wi-Fi or the API
fails. The canned heart-failure answer deliberately contains one made-up medicine and one item with a
missing frequency, so the demo shows the verifier catching problems.
"""

import json
import re
from types import SimpleNamespace

from .plan import DISCLAIMER_EN
from .schemas import ExtractionDraft, PlanDraft


def _med(name, dose, route, freq, dur, purpose, instr, status, quote, previous_dose=None):
    return dict(name=name, dose=dose, route=route, frequency=freq, duration=dur, purpose=purpose,
                instructions=instr, status=status, source_quote=quote, previous_dose=previous_dose)


def _fu(what, who, when, quote, contact=None):
    return dict(what=what, with_whom=who, when=when, source_quote=quote, contact=contact)


def _ws(symptom, action, quote):
    return dict(symptom=symptom, action=action, source_quote=quote)


def _rs(cat, instruction, quote):
    return dict(category=cat, instruction=instruction, source_quote=quote)


HEART = dict(
    diagnosis_summary="Admitted for worsening shortness of breath and leg swelling from congestive heart failure.",
    medications=[
        _med("Furosemide", "40 mg", "oral", "every morning", None, "a water pill to remove extra fluid",
             "take it early in the day", "new", "Furosemide (Lasix) 40 mg tablet - take 1 tablet by mouth every morning"),
        _med("Metoprolol succinate ER", "25 mg", "oral", "once daily", None, None,
             "do not crush or chew; do not stop suddenly", "new",
             "Metoprolol succinate ER 25 mg tablet - take 1 tablet by mouth once daily"),
        _med("Lisinopril", "10 mg", "oral", "once daily", None, None,
             "dose lowered because of a kidney blood test", "changed",
             "Lisinopril: DECREASE from 20 mg to 10 mg once daily", previous_dose="20 mg"),
        _med("Atorvastatin", "40 mg", "oral", "1 tablet at bedtime", None, None, None, "continue",
             "Atorvastatin 40 mg - 1 tablet at bedtime"),
        # Planted problem 1: frequency missing -> needs the patient's check.
        _med("Aspirin", "81 mg", "oral", None, None, None, "take with food", "continue",
             "Aspirin 81 mg - 1 tablet daily with food"),
        _med("Ibuprofen", None, None, None, None, None, "can make heart failure worse and hurt your kidneys", "stop",
             "Ibuprofen (Advil, Motrin)"),
        _med("Naproxen", None, None, None, None, None, "can make heart failure worse and hurt your kidneys", "stop",
             "naproxen (Aleve)"),
        # Planted problem 2: a made-up medicine. The document never mentions it.
        _med("Potassium chloride", "20 mEq", "oral", "once daily", None, None, None, "new",
             "Potassium chloride 20 mEq tablet - 1 tablet daily"),
    ],
    follow_ups=[
        _fu("Cardiology clinic visit", "Dr. Okafor", "within 7 days", "Cardiology clinic (Dr. Okafor): within 7 days.",
            contact="555-0142 (to schedule)"),
        _fu("Blood test (kidney function and potassium)", None, "in 1 week, before your clinic visit",
            "Blood test (kidney function and potassium): in 1 week"),
        _fu("Primary care visit", "Dr. Hale", "within 2 weeks", "Primary care (Dr. Hale): within 2 weeks."),
    ],
    warning_signs=[
        _ws("Gain more than 3 pounds in 1 day or 5 pounds in 1 week", "Call your doctor",
            "Gain more than 3 pounds in 1 day or 5 pounds in 1 week"),
        _ws("More swelling in your feet, ankles or belly", "Call your doctor",
            "Have more swelling in your feet, ankles or belly"),
        _ws("Feel dizzy or lightheaded, or have a fast heartbeat", "Call your doctor",
            "Feel dizzy or lightheaded, or have a fast heartbeat"),
        _ws("Need more pillows to sleep or wake up short of breath", "Call your doctor",
            "Need more pillows to sleep or wake up short of breath"),
        _ws("Chest pain or pressure that does not go away", "Call 911", "Chest pain or pressure that does not go away"),
        _ws("Severe trouble breathing, fainting, or coughing up pink, foamy mucus", "Call 911",
            "Severe trouble breathing, fainting, or coughing up pink, foamy mucus"),
    ],
    restrictions=[
        _rs("diet", "Limit sodium (salt) to 2,000 mg per day; do not add salt to food", "Limit sodium (salt) to 2,000 mg per day"),
        _rs("diet", "Limit fluids to 1.5 liters (about 6 cups) per day", "Limit fluids to 1.5 liters (about 6 cups) per day"),
        _rs("monitoring", "Weigh yourself every morning after using the bathroom and before eating, and write it down",
            "Weigh yourself every morning after using the bathroom and before eating"),
        _rs("medication_limit", "For pain you may use acetaminophen (Tylenol), no more than 3,000 mg in one day",
            "For pain you may use acetaminophen (Tylenol), no more than 3,000 mg in one day."),
        _rs("activity", "Walk for short periods as you feel able; rest if short of breath",
            "Walk for short periods as you feel able"),
    ],
    unclear_items=["The paper does not say what to do if you miss a dose of a medicine."],
)

PNEUMONIA = dict(
    diagnosis_summary="Community-acquired pneumonia (infection in the right lung). Treated with IV antibiotics for 3 days, "
                      "then switched to pills.",
    medications=[
        _med("Amoxicillin-clavulanate", "875/125 mg", "oral", "twice a day with meals", "4 more days (last dose on the evening of 10/19)",
             None, "finish ALL tablets even if you feel better", "new",
             "Amoxicillin-clavulanate (Augmentin) 875/125 mg: 1 tablet by mouth twice a day with meals for 4 more days (last dose on the evening of 10/19)."),
        _med("Prednisone", "40 mg for 2 days, then 20 mg for 2 days", "oral", "daily", None, None,
             "take in the morning with food; can raise blood sugar", "new",
             "Prednisone taper: 40 mg daily for 2 days, then 20 mg daily for 2 days, then stop."),
        _med("Guaifenesin", "600 mg", "oral", "every 12 hours as needed for cough/chest congestion", None, None, None, "new",
             "Guaifenesin 600 mg: 1 tablet every 12 hours as needed for cough/chest congestion"),
        _med("Metformin", "1000 mg", "oral", "twice daily with meals", None, None, "OK to resume tonight", "continue",
             "Metformin 1000 mg: continue 1 tablet twice daily with meals"),
        _med("Lisinopril", "20 mg", "oral", "once daily", None, None, None, "continue",
             "Lisinopril 20 mg: continue once daily"),
        _med("Albuterol inhaler", "2 puffs", "inhaled", "every 4-6 hours only if wheezing or short of breath", None, None, None, "new",
             "Albuterol inhaler: 2 puffs every 4-6 hours only if wheezing or short of breath"),
    ],
    follow_ups=[
        _fu("Primary care visit", "Dr. Singh", "in 5 to 7 days", "Primary care, Dr. Singh - in 5 to 7 days."),
        _fu("Chest X-ray", None, "in 6 weeks", "Chest X-ray - in 6 weeks to confirm the pneumonia has cleared."),
    ],
    warning_signs=[
        _ws("trouble breathing, chest pain, confusion, lips or fingertips turning blue, or a fever above 101 F that lasts "
            "more than 48 hours", "Return to the Emergency Department or call 911",
            "Return to the Emergency Department or call 911 for: trouble breathing, chest pain, confusion, "
            "lips or fingertips turning blue, or a fever above 101 F that lasts more than 48 hours."),
        _ws("worsening cough, vomiting that keeps you from taking your pills, rash or severe diarrhea (possible antibiotic "
            "reaction)", "Call your doctor",
            "Call your doctor for: worsening cough, vomiting that keeps you from taking your pills, "
            "rash or severe diarrhea (possible antibiotic reaction)."),
        _ws("blood sugar readings above 300", "Call your doctor", "Call your doctor if readings are above 300."),
    ],
    restrictions=[
        _rs("other", "Check your blood sugar at least twice daily (before breakfast and before dinner) until the prednisone is finished",
            "check your blood sugar at least twice daily (before breakfast and"),
        _rs("other", "Do not take over-the-counter cough suppressants containing codeine",
            "Do NOT take: over-the-counter cough suppressants containing codeine."),
        _rs("activity", "Rest at home for several days and return to normal activity slowly",
            "Rest at home for several days. Return to normal activity slowly."),
        _rs("diet", "Drink plenty of fluids unless told otherwise", "Drink plenty of fluids unless told otherwise."),
        _rs("other", "Do not smoke and avoid smoke exposure", "Do not smoke and avoid smoke exposure."),
    ],
    unclear_items=[],
)

HIP = dict(
    diagnosis_summary="Left total hip replacement surgery.",
    medications=[
        _med("Apixaban", "2.5 mg", "oral", "twice daily", "35 days after surgery", "to prevent blood clots",
             "do not skip doses", "new", "Apixaban (Eliquis) 2.5 mg - 1 tablet by mouth twice daily for 35 days after surgery."),
        _med("Acetaminophen", "1,000 mg", "oral", "every 8 hours on a schedule", "first 2 weeks, then as needed", None,
             "no more than 3,000 mg in 24 hours", "new",
             "Acetaminophen 1,000 mg every 8 hours on a schedule for the first 2 weeks"),
        _med("Oxycodone", "5 mg", "oral", "every 6 hours ONLY IF pain is not controlled by acetaminophen", None, None,
             "may cause drowsiness; no driving or alcohol", "new",
             "Oxycodone 5 mg: 1 tablet every 6 hours ONLY IF pain is not controlled by acetaminophen."),
        _med("Docusate", "100 mg", "oral", "twice daily while taking oxycodone", None, None, None, "new",
             "Docusate 100 mg twice daily while taking oxycodone."),
        _med("Senna", "8.6 mg", None, "at bedtime, only if no bowel movement in 2 days", None, None, None, "new",
             "Add senna 8.6 mg at bedtime if no bowel movement in 2 days."),
    ],
    follow_ups=[
        _fu("Surgeon visit", "Dr. Moreno", "2 weeks after surgery (06/26)", "Surgeon Dr. Moreno, 2 weeks after surgery (06/26)."),
        _fu("Home physical therapy", None, "within 2 days after you get home (the agency will call you)",
            "Home physical therapy begins within 2 days after you get home; the agency will call you."),
    ],
    warning_signs=[
        _ws("sudden shortness of breath, chest pain, coughing blood, signs of stroke, bleeding that will not stop, or if you "
            "fall and cannot get up or your leg looks shortened or turned", "Call 911",
            "CALL 911 if: sudden shortness of breath, chest pain, coughing blood, signs of stroke, bleeding "
            "that will not stop, or if you fall and cannot get up or your leg looks shortened or turned."),
        _ws("temperature over 101.5 F, redness, warmth or drainage at the incision, increasing pain, or calf pain/swelling in "
            "either leg", "Call the office (555-0188)",
            "CALL THE OFFICE (555-0188) if: temperature over 101.5 F, redness, warmth or drainage at the "
            "incision, increasing pain, or calf pain/swelling in either leg."),
    ],
    restrictions=[
        _rs("activity", "Do not bend your hip past 90 degrees (no low chairs or toilets without a raised seat)",
            "Do NOT bend your hip past 90 degrees (no low chairs or toilets without a raised seat)."),
        _rs("activity", "Do not cross your legs or ankles", "Do NOT cross your legs or ankles."),
        _rs("activity", "Do not twist your body toward the operated leg", "Do NOT twist your body toward the operated leg."),
        _rs("activity", "Walk with the walker as taught by physical therapy; short walks 4-5 times a day",
            "Walk with the walker as taught by physical therapy; short walks 4-5 times a day."),
        _rs("activity", "No driving until cleared at your follow-up visit", "No driving until cleared at your follow-up visit."),
        _rs("wound_care", "Keep the dressing clean and dry", "Keep the dressing clean and dry."),
        _rs("wound_care", "You may shower on 06/20 (7 days); no baths, pools or hot tubs for 6 weeks",
            "You may shower on 06/20 (7 days); no baths, pools or hot tubs for 6 weeks."),
        _rs("wound_care", "Do not put creams or ointments on the incision", "Do not put creams or ointments on the incision."),
        _rs("medication_limit", "Avoid ibuprofen and naproxen while on apixaban", "Avoid ibuprofen and naproxen while on apixaban."),
    ],
    unclear_items=[],
)

GALLBLADDER = dict(
    diagnosis_summary="Laparoscopic gallbladder removal surgery.",
    medications=[
        _med("Tylenol", "500 mg (2 tablets)", "oral", "every 6 hours", None, "for pain", None, "new",
             "Tylenol (acetaminophen) 500 mg - take 2 tablets by mouth every 6 hours for pain."),
        _med("Percocet", "5/325 mg (1 tablet)", "oral", "every 6 hours ONLY IF your pain is severe", None, None,
             "can cause drowsiness; do not drive", "new",
             "Percocet (oxycodone/acetaminophen) 5/325 mg - take 1 tablet by mouth every 6 hours"),
        _med("Motrin IB", "200 mg", None, "every 8 hours with food if you have swelling", None, None, None, "new",
             "Motrin IB (ibuprofen) 200 mg - take 1 tablet every 8 hours with food if you have swelling."),
        _med("Ondansetron", "4 mg", None, "every 8 hours only if you feel sick to your stomach", None, None, None, "new",
             "Ondansetron 4 mg - take 1 tablet every 8 hours only if you feel sick to your stomach."),
        _med("Docusate", "100 mg", None, "twice daily with meals", None, "to keep your bowels moving", None, "new",
             "Docusate 100 mg - take 1 capsule twice daily with meals to keep your bowels moving."),
        _med("Warfarin", "5 mg", None, "1 tablet at bedtime", None, None, "your clinic will check your INR blood test", "continue",
             "Warfarin 5 mg: continue 1 tablet at bedtime."),
        _med("Lisinopril", "10 mg", None, "every morning", None, None, None, "continue",
             "Lisinopril 10 mg: continue 1 tablet every morning."),
        _med("Advil", None, None, None, "until your surgeon says it is safe", None, None, "stop",
             "Advil (ibuprofen) and aspirin until your surgeon says it is safe."),
        _med("Aspirin", None, None, None, "until your surgeon says it is safe", None, None, "stop",
             "aspirin until your surgeon says it is safe"),
    ],
    follow_ups=[
        _fu("Surgeon visit", "Dr. Ibarra", "2 weeks after surgery", "Surgeon, Dr. Ibarra: 2 weeks after surgery."),
        _fu("INR blood test", None, "in 3 days", "INR blood test: in 3 days."),
    ],
    warning_signs=[
        _ws("chest pain, trouble breathing, or vomiting blood", "Call 911",
            "CALL 911 if: chest pain, trouble breathing, or vomiting blood."),
        _ws("fever over 101 F, yellow skin or eyes, severe belly pain, or bleeding from the wounds", "Call the office",
            "CALL THE OFFICE if: fever over 101 F, yellow skin or eyes, severe belly pain, or bleeding from the wounds."),
    ],
    restrictions=[
        _rs("wound_care", "You may shower after 48 hours; do not soak in a bath for 2 weeks",
            "You may shower after 48 hours. Do not soak in a bath for 2 weeks."),
        _rs("activity", "No lifting more than 10 pounds for 4 weeks", "No lifting more than 10 pounds for 4 weeks."),
    ],
    unclear_items=["The paper lists Motrin IB (ibuprofen) for swelling but also says to stop Advil (ibuprofen). "
                   "Ask your surgeon which instruction is right."],
)

_MARKERS = [("Furosemide", HEART), ("Augmentin", PNEUMONIA), ("Apixaban", HIP), ("Percocet", GALLBLADDER)]


class DemoLabelSource:
    """Stand-in for FDA label text, so demo mode needs no internet.

    The sentences below are WRITTEN FOR THE DEMO and are not real label text. They are tagged as such
    in the UI via ``source_name``.
    """

    source_name = "Demo sample text (not a real FDA label)"
    _TEXT = {
        "warfarin": "Regular use of acetaminophen may increase the effect of warfarin, so your INR may need closer monitoring. "
                    "Medicines such as ibuprofen can raise the risk of bleeding when taken with warfarin.",
        "lisinopril": "Aspirin may reduce the blood-pressure-lowering effect of lisinopril in some patients.",
    }

    def interactions_text(self, ingredient: str):
        return self._TEXT.get(ingredient)


class DemoExtractionClient:
    """Looks like anthropic.Anthropic() to Extractor, answers from canned data."""

    def __init__(self):
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        text = kwargs["messages"][0]["content"]
        for marker, data in _MARKERS:
            if marker in text:
                return SimpleNamespace(parsed_output=ExtractionDraft.model_validate(data), stop_reason="end_turn")
        empty = dict(diagnosis_summary=None, medications=[], follow_ups=[], warning_signs=[], restrictions=[],
                     unclear_items=["Demo mode only understands the three built-in sample documents."])
        return SimpleNamespace(parsed_output=ExtractionDraft.model_validate(empty), stop_reason="end_turn")


_GENERIC_WHY = {
    "metoprolol": "Helps slow your heart rate so your heart does not have to work as hard.",
    "lisinopril": "Helps lower blood pressure and protects your heart.",
    "atorvastatin": "Helps lower cholesterol.",
    "aspirin": "Helps prevent blood clots.",
    "metformin": "Helps control blood sugar.",
    "albuterol": "Helps open the airways to make breathing easier.",
}


_ROUTE_PLAIN = {"oral": "by mouth", "sublingual": "under the tongue", "inhaled": "inhaled", "topical": "on the skin",
                "ophthalmic": "in the eye", "otic": "in the ear", "nasal": "in the nose", "rectal": "rectally",
                "subcutaneous": "as an injection under the skin", "intramuscular": "as an injection into a muscle",
                "intravenous": "through a vein (IV)", "other": None}


class DemoPlanClient:
    """Writes a plain (English) plan from the confirmed data with simple rules, no LLM."""

    def __init__(self):
        self.messages = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs):
        content = kwargs["messages"][0]["content"]
        code = re.search(r"Target language: .*\((\w+)\)", content).group(1)
        data = json.loads(re.search(r"<confirmed_data>\n(.*)\n</confirmed_data>", content, re.S).group(1))
        note = "" if code == "en" else "[Demo mode: real translation needs an API key] "

        def med(m):
            if m["status"] == "stop":
                how = f"Stop taking {m['name']}" + (f" {m['duration']}" if m.get("duration") else "") + "."
            else:
                bits = [m["dose"], _ROUTE_PLAIN.get(m["route"]), m["frequency"], f"for {m['duration']}" if m["duration"] else None]
                how = "Take " + " ".join(b for b in bits if b) + "."
                if m["status"] == "changed":
                    how = "Your dose changed" + (f" from {m['previous_dose']}" if m.get("previous_dose") else "") + ". " + how
            if m["instructions"]:
                how += f" {m['instructions'][0].upper()}{m['instructions'][1:]}."
            why = m["purpose"] or next((v for k, v in _GENERIC_WHY.items() if k in m["name"].lower()), None)
            return dict(id=m["id"], how_to_take=note + how, why_taking=why)

        def fu(f):
            text = " ".join(p for p in [f["what"], f"with {f['with_whom']}" if f["with_whom"] else None, f["when"]] if p) + "."
            if f.get("contact"):
                text += f" Phone: {f['contact']}."
            return dict(id=f["id"], plain_text=note + text)

        def ws(w):
            return dict(id=w["id"], plain_text=note + f"{w['action']} if you have: {w['symptom']}.")

        def rs(r):
            return dict(id=r["id"], plain_text=note + r["instruction"] + ".")

        why = data["diagnosis_summary"] or "your hospital stay"
        draft = PlanDraft(
            summary=note + f"You were in the hospital because of: {why} This plan lists your medicines, appointments, warning signs and care at home.",
            medications=[med(m) for m in data["medications"]],
            follow_ups=[fu(f) for f in data["follow_ups"]],
            warning_signs=[ws(w) for w in data["warning_signs"]],
            restrictions=[rs(r) for r in data["restrictions"]],
            disclaimer=note + DISCLAIMER_EN,
        )
        return SimpleNamespace(parsed_output=draft, stop_reason="end_turn")

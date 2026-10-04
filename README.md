# MedBridge

An AI discharge-instruction coach. A patient uploads their hospital discharge paperwork;
MedBridge turns it into a plain-language plan, then checks in by SMS and escalates to a human
when something looks wrong.

> **Not a medical device.** MedBridge only restates what the patient's own clinicians wrote.
> It does not diagnose, prescribe, or give new medical advice. All sample documents in this
> repo are **synthetic**; never commit real patient data.

## Roadmap

| Phase | What | Status |
|---|---|---|
| 1 | Upload -> extract meds/follow-ups/warning signs/restrictions as JSON, each with a source quote that code verifies | **done** |
| 2 | Confirm screen + plain-language plan (+ translation) | next |
| 3 | Drug interaction / duplicate check (RxNav) + daily schedule | |
| 4 | Twilio SMS check-ins, reply parsing, red-flag rules, alerts | |
| 5 | Caregiver/nurse dashboard, adherence timeline | |
| 6 | Polish, demo video | |

## Run Phase 1

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt

pytest                                   # no API key needed; the LLM is faked in tests

export ANTHROPIC_API_KEY=...             # only needed for the real thing
python scripts/try_extract.py samples/01_heart_failure.txt
uvicorn app.main:app --reload            # then open http://127.0.0.1:8000/docs
```

See [docs/phase-1.md](docs/phase-1.md) for how it works and why.

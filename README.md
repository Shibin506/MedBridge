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
| 2 | Confirm screen + plain-language plan (+ translation), demo mode | **done** |
| 3 | Drug interaction / duplicate check (RxNav) + daily schedule | next |
| 4 | Twilio SMS check-ins, reply parsing, red-flag rules, alerts | |
| 5 | Caregiver/nurse dashboard, adherence timeline | |
| 6 | Polish, demo video | |

## Quickest way (no API key needed: demo mode)

Needs Python 3.10+ and Node.js 20+.

```bash
git clone https://github.com/Shibin506/MedBridge && cd MedBridge
./scripts/run-demo.sh
```

Then open http://localhost:3000. Press Ctrl+C to stop. The first run takes a couple of minutes to install things.

## Run it step by step (no API key needed: demo mode)

```bash
# terminal 1: backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                   # 32 tests, the LLM is faked
MEDBRIDGE_DEMO=1 uvicorn app.main:app --port 8000

# terminal 2: frontend
cd frontend
npm install
npm run build && npm run start           # or: npm run dev   ->  http://localhost:3000
```

Open http://localhost:3000 and click one of the fictional examples. Demo mode answers from pre-written
data, so it also works as a hackathon fallback if the Wi-Fi or the API fails.

## Run it for real

```bash
export ANTHROPIC_API_KEY=...             # never commit this
uvicorn app.main:app --port 8000         # without MEDBRIDGE_DEMO
python scripts/try_extract.py samples/01_heart_failure.txt   # extraction only, prints a report
```

## How it works

- [docs/phase-1.md](docs/phase-1.md): upload -> verified extraction
- [docs/phase-2.md](docs/phase-2.md): confirm screen -> plain-language plan

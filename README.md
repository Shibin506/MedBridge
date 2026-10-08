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
| 3 | Daily schedule + safety check (duplicates, stopped-but-listed, label-based interaction hints) | **done** (live lookups need a quick check, see docs/phase-3.md) |
| 4 | Daily text check-ins (phone simulator + real Twilio), red-flag rules from the patient's own paper, care-team alerts, acetaminophen daily-total check | **done** (real texts need a quick live check, see docs/phase-4.md) |
| 5 | Care-team dashboard: all patients ranked by urgency, alert inbox with notes (audit trail), patient pages, example patients, optional access code | **done** (docs/phase-5.md) |
| 6 | Polish, demo video | |

## Quickest way (no API key needed: demo mode)

Needs **Python 3.10+** (macOS ships 3.9, which is too old; `brew install python@3.12` or use python.org) and Node.js 20+.

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
pytest                                   # 468 tests, the LLM is faked
MEDBRIDGE_DEMO=1 uvicorn app.main:app --port 8000

# terminal 2: frontend
cd frontend
npm install
npm run build && npm run start           # or: npm run dev   ->  http://localhost:3000
```

Open http://localhost:3000 and click one of the fictional examples. Demo mode answers from pre-written
data, so it also works as a hackathon fallback if the Wi-Fi or the API fails.

## Run it with the real AI (free Groq key)

1. Create a free key at https://console.groq.com/keys (it starts with `gsk_`) and click **Copy**.
2. `./scripts/set-key.sh`, then paste it with Cmd+V and press Enter. It saves `.env` and tests the key.
3. `./scripts/run-demo.sh --live`

Gemini and Claude also work. Details, Twilio setup and privacy notes: [docs/setup-keys.md](docs/setup-keys.md).
**Free-tier AI services may use what you send. Only use the fictional sample documents until you have a paid/private setup.**

## How it works

- [docs/phase-1.md](docs/phase-1.md): upload -> verified extraction
- [docs/phase-2.md](docs/phase-2.md): confirm screen -> plain-language plan
- [docs/phase-3.md](docs/phase-3.md): daily schedule and safety check
- [docs/phase-4.md](docs/phase-4.md): text check-ins, alerts, and the phone simulator
- [docs/phase-5.md](docs/phase-5.md): the care-team dashboard

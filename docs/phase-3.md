# Phase 3: a daily schedule and a safety check

**Goal:** after the patient confirms their list, show *when* to take each medicine and warn about the
mistakes that cause most medicine accidents at home: taking the same ingredient twice, following an
instruction that was cancelled, and risky combinations.

**Everything in this phase is plain code, not the AI.** That makes it testable and predictable.

```
confirmed list --POST /schedule--> DailySchedule
               --POST /safety----> SafetyReport      (both use the same "patient must confirm first" gate as /plan)
```

## The schedule (`app/schedule.py`)

Turns the paper's words into clock times. **Rule: never guess.** If a timing is not a pattern we are sure
about, it goes under "Ask your care team about timing" with the reason.

| Paper says | We show |
|---|---|
| once daily / every morning | 8:00 AM |
| at bedtime | 9:30 PM |
| twice daily (with meals) | 8:00 AM and 8:00 PM (8:00 AM and 6:30 PM) |
| every 12 / 8 / 6 hours | 8 AM + 8 PM / 6 AM + 2 PM + 10 PM / 6 AM, noon, 6 PM, midnight (plus a note to ask about night doses) |
| only if / as needed / if you have... | "Only when needed" list, **no clock time** |
| "40 mg for 2 days, then 20 mg for 2 days, then stop" | a day-by-day step-down |
| every 4-6 hours (no "as needed"), weekly, every 3 days, anything unusual, no frequency | "Ask your care team", with the reason |
| status = stop | not scheduled |

Bugs found while building (and fixed, with tests): a step-down was shown twice because the dose and the
quote both contained it; "twice daily, take with food" correctly maps to breakfast and dinner.

## The safety check (`app/drugs.py`, `app/safety.py`)

1. **Which ingredients are in each medicine?** Tylenol -> acetaminophen. Percocet -> oxycodone + acetaminophen.
   Order: a built-in brand table -> (optional) NIH RxNorm -> otherwise the written name is assumed to be generic.
2. **Duplicates:** two active medicines share an ingredient (Tylenol + Percocet = acetaminophen twice).
3. **Stopped-but-listed:** the paper says stop Advil (ibuprofen), but Motrin IB (ibuprofen) is still on the list.
4. **Interaction hints:** if the FDA label of drug A names drug B in its "drug interactions" section, we show **that
   sentence word for word** with its source. Stopped medicines are ignored.

### Honest limits (also shown to the patient)

- It only finds interactions a label names **explicitly**. It does not know classes ("NSAIDs") or severity.
  *No hint does not mean safe.* The screen says so every time.
- If the internet lookup fails, the screen says **"Interactions were NOT checked"**. A failed lookup is never
  shown as "no problems". Duplicate and stopped-medicine checks work offline.
- The NIH's old free drug-interaction service was shut down in 2024 (as far as I know), which is why this uses
  FDA label text instead. This is a hint, not a clinical interaction checker. A real product would license one.
- It does not yet add up daily doses (for example, total acetaminophen across products). That is a good next feature.

## Demo mode

Works fully offline. Interaction sentences come from `DemoLabelSource` and are labelled
**"Demo sample text (not a real FDA label)"** on screen. Sample 04 (gallbladder surgery) is built to trigger
every finding: a duplicate, a conflict, two interaction hints, an as-needed list and a bedtime dose.

## Checking the live services

The sandbox this was built in cannot reach the NIH or FDA, so the live parts were tested only against
hand-written fixtures in their documented formats. **Run this once on a computer with internet:**

```bash
cd backend && source .venv/bin/activate
pip install -r requirements.txt        # (httpx is required)
python scripts/check_live_lookups.py
```

It prints PASS/FAIL for each lookup. If something fails, the code falls back safely (see above).

## Tests

93 backend tests. The suites for the schedule and the safety checks include the failure paths: outage,
unknown names, ambiguous timing, stopped medicines. I also broke the code on purpose twice to check that the
tests notice (they did).

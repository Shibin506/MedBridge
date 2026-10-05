# Phase 2: the patient checks it, then gets a plan

**Goal:** never show a patient a plan built on something they have not checked, and write that plan in
words they understand, in their language.

## The flow

```
POST /extract  ->  ExtractionResult (+ the paper's text)
                       |
        Confirm screen (frontend)  <- patient checks, edits, removes, ticks "I have read this"
                       |
POST /plan  ->  THE GATE (code)  ->  LLM writes friendly wording  ->  CHECKS (code)  ->  PatientPlan
```

## Same rule as Phase 1: the LLM writes words, code owns facts

| Decision | Who makes it |
|---|---|
| Is this item grounded in the paper? | code (`verify.py`) |
| May we build a plan yet? | code (`readiness_problems`) |
| Medicine name, dose, status (new/stop/...) shown in the plan | code copies them from the confirmed data |
| Was any item dropped or invented? | code (`check_plan`: ids must match exactly) |
| Did every number (40 mg, 35 days) survive? | code (`check_plan`) |
| Does every "call 911" item still say 911? | code (`check_plan`) |
| Is a "why you take it" sentence from the paper or general knowledge? | code (`why_source`: from the paper only if the paper gave a purpose) |
| Is something missing from the paper (dose, how often)? | code (`missing_info`) |
| Friendly wording, translation, reading level | the LLM |

If the checks fail, we retry once and tell the model exactly what was wrong. A second failure returns an
error instead of a plan we cannot vouch for.

## The gate

`POST /plan` answers **409** until:
- every item that `needs_confirmation` has `patient_confirmed` (the patient clicked "This is right" or edited it),
- the patient has ticked that they read the "please check with your care team" notes,
- at least one item remains.

The button in the UI is only a convenience. The server enforces it, so a bug or a hand-made request
cannot skip the patient's check.

## The frontend (`frontend/`)

Next.js (App Router) + TypeScript, plain CSS. Large text and high contrast on purpose: many patients are older.

| File | Role |
|---|---|
| `app/page.tsx` | Holds the state: upload -> confirm -> plan |
| `components/UploadStep.tsx` | Upload or pick a fictional sample |
| `components/ConfirmStep.tsx` | "Your paper" next to the items; click an item to highlight its quote |
| `components/ItemCard.tsx` | One item: confirm / edit / remove, with a green or amber state |
| `components/PlanStep.tsx` | The plan; Stop-taking box; 911 items in red; print; language switch; right-to-left for Arabic |
| `lib/highlight.ts` | Finds a quote in the paper even if line breaks differ |
| `next.config.mjs` | Forwards `/api/*` to the FastAPI server (no CORS setup needed) |

## Demo mode (`MEDBRIDGE_DEMO=1`, `app/demo.py`)

Two fake "AI clients" answer from canned data, so everything runs with no key. The heart-failure example has
two planted problems on purpose: a **made-up medicine** (the checker flags it as "not found in the document") and an
**item missing its frequency**. Great for showing the safety idea in a demo.

## Tests

- Backend: 32 tests (`pytest`), including the gate, every plan check, the retry, and a full extract -> confirm -> plan run through the API.
- UI: verified by driving the real app in a headless browser (upload -> blocked -> highlight -> remove fake medicine
  -> confirm -> plan -> language switch -> right-to-left). The script is not in the repo yet.

## Known limits

- The buttons and headings in the UI are English only; the plan text itself is translated. Machine translation of
  medical text has not been reviewed by native speakers: the plan always shows the English "From your paper" original.
- Nothing is saved yet: refresh the page and you start over (storage arrives with SMS in Phase 4).
- Real-model quality (how often the retry triggers, translation quality) is untested until you run it with a key.

## Review round after the first live run (what a real AI run taught us)

The first run on the heart-failure paper showed what the AI gets wrong, so these were added:

| Problem seen | Fix |
|---|---|
| "For pain you may use acetaminophen, no more than 3,000 mg in one day" was dropped | Prompt now asks for permissions/limits (category `medication_limit`); patient can also **add anything the AI missed** (marked "Added by you") |
| Phone number ("Call 555-0142") dropped | New `contact` field; code checks the number really is in the paper; the plan must repeat it |
| Lisinopril "10 mg" lost "was 20 mg" | New `previous_dose` field; the plan must mention the old dose |
| A wrong number (400 mg for 40 mg) would still show "Found in your paper" | **Number check:** every number in dose / how often / duration must be in the supporting quote, else the item is flagged |
| "Everything has been checked" was false reassurance | Honest wording, and a **review box that is always required** (the server refuses a plan without it, even when nothing is flagged) |
| "for for 35 days", "naproxen" lowercase, daily weighing filed under "other" | duration cleaned in the data model, names capitalised, new `monitoring` category |

## Second review round (from the gallbladder paper, real model)

The real model dropped three details and our checker said "nothing wrong". Each now has a safety net that does not rely on the AI:

| What the AI dropped | Safety net |
|---|---|
| "take **2 tablets**" -> dose written as "500 mg" (half the real amount) | **Tablet-count check:** if the quote says "N tablets/puffs/..." (N more than 1) and the dose/schedule/instructions never mention N, the item is flagged |
| "...**until your surgeon says it is safe**" -> a temporary stop looked permanent | **"until" check:** the quote's "until ..." must appear in the item, and a stopped medicine now reads "Do not take this medicine until ..." |
| "You may shower after 48 hours" never extracted | **Coverage check** (`coverage.py`): sentences of the paper that nothing extracted covers are listed as "Lines of your paper we did not use", with a Show in paper button |

The coverage check is a hint, not a guarantee. It may list harmless explanations (reasons, side effects) and it can miss a dropped line
whose words appear elsewhere. The prompt also now asks for tablet counts, `until` conditions and one item per instruction sentence.

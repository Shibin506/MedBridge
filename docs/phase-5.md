# Phase 5: the care-team dashboard

**Goal:** one nurse or caregiver can watch many patients at once. The patient side tells each person what to do; this side tells the care
team **who to call first**, and keeps a record of what was done.

Open it with the **Care team** button at the top (or `http://localhost:3000/#team`). It refreshes every 10 seconds, so real text replies
show up without reloading.

```
many patients' check-ins --> alerts, weights, answers (SQLite)
   GET /dashboard  --> code sorts: Emergency > Call today > Please read > Texts stopped > No open alerts
   nurse clicks "Mark as seen" + note --> saved with who and when --> "typical time to respond" updates
```

## What you see

| Part | What it shows |
|---|---|
| Tiles | How many patients are in each status. Click one to filter the list. |
| **Needs a person** | Every open alert, worst first, longest-waiting first. Each has a fixed **next step** and a **Mark as seen** form with a note. |
| Patients table | Status, one-line reason, weight (with a tiny trend line), how many reminders were confirmed, and when we last heard from them. |
| Patient page | That patient's alerts, the whole text conversation (read-only), weight chart, adherence, **the plan they confirmed**, and the rules behind their alerts. |
| Recently handled | Alerts that were marked seen, with who, when and the note. This is the audit trail. |

## Who decides what

- **Status and order are plain code** (`dashboard.py`). No AI. The worst open alert sets the patient's status; among equals, whoever has waited longest is first, then alphabetical so the list never jumps around.
- **Silence is not hidden.** Two unanswered reminders in a row raise an alert (Phase 4). A patient who texts STOP is shown as **Texts stopped**, because nobody is watching them automatically any more: a person should call.
- **"No open alerts" means exactly that.** It does not mean "healthy".
- **Next steps are fixed, operational text** ("Call the patient now. If there is no answer, follow your clinic's emergency protocol."). They never say what is medically wrong or what to prescribe. Your clinic's own protocol comes first.
- **One message, one alert.** "I have chest pain and trouble breathing" is one emergency alert, not two.
- **Marking seen never overwrites.** A second click keeps the first person's note and time.

## Access code

This page lists every patient, so it can be protected:

1. Add a line `MEDBRIDGE_TEAM_KEY=` followed by letters and digits to `.env` (a long random one).
2. Restart. The page now asks for the code (kept only in that browser tab) and the server rejects requests without it (`X-Team-Key` header).

Without the setting the page is open and says so. That is fine on your own computer and **not** fine on the internet.
This is a first step, not real security: there are no individual accounts, no lockout after wrong guesses, and no encryption of the database.
Still **no real patient data** (see Phase 4).

## Example patients

With no patients yet, **Load 6 example patients** fills the page. They are made up, play a few days through the *real* check-in engine
(so the alerts are the ones real replies would cause), and all have ids starting `demo-`. **Remove the examples** deletes only those.

| Example | Story | Shows as |
|---|---|---|
| James Carter | pneumonia; "chest pain and trouble breathing" | Emergency |
| Maria Gonzalez | heart failure; ankles swollen, weight 172 -> 177 | Call today |
| Robert Singh | gallbladder surgery; stops answering reminders | Please read |
| Aisha Khan | pneumonia; replies STOP | Texts stopped |
| Linda Park | hip replacement; drainage alert, already handled with a nurse's note | No open alerts |
| David Lee | heart failure; stable | No open alerts |

## The files

- `backend/app/dashboard.py`: statuses, ordering, alert rows, patient page data
- `backend/app/demo_patients.py`: the scripted example patients
- `backend/app/store.py`: alerts now keep who/when/note; older database files are upgraded automatically
- `backend/app/main.py`: `GET /dashboard`, `GET /dashboard/patients/{id}`, `POST /alerts/{id}/ack` (note + name), `POST|DELETE /demo/patients`
- `frontend/components/CareTeamDashboard.tsx`, `PatientDetail.tsx`, `AlertCard.tsx`
- `backend/tests/test_dashboard.py`

## Not built yet

Per-nurse accounts and assignment, escalation if an
emergency alert sits unseen, and a way for the care team to text a patient back.

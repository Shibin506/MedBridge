# Phase 4: reminders, daily check-ins, and alerts

**Goal:** after the patient confirms their plan, text them when each medicine is due, check in every morning, and make sure a worrying
reply reaches a person fast. The on-screen **phone simulator** needs no accounts; real texts use Twilio.

```
confirmed plan --POST /patients--> patient saved (SQLite)
   "Next text" (or a timer later) --> reminder / morning check-in --> patient's phone
   patient's reply --> CODE decides --> reply text + (maybe) care-team alert
```

## Who decides what

| Decision | Who |
|---|---|
| What to ask and when | code, from the confirmed schedule and the patient's own warning signs |
| Is a reply an emergency / call-the-doctor / needs-a-person-to-read | **code** (`redflags.py`), never an AI |
| Weight limit ("more than 3 pounds in 1 day") | read from the **patient's own paper** by code |
| The wording of every reply | fixed templates (`checkins.py`) |

## Safety rules built in

- **Rules come from the patient's paper.** Each confirmed warning sign ("Call 911" / "Call your doctor") is matched to a symptom concept,
  so "my ankles are swollen" matches "more swelling in your feet, ankles or belly".
- **Universal emergencies always mean 911,** even if the paper does not list them: chest pain or pressure, fainting, stroke signs,
  coughing/vomiting blood, a closing throat, a severe inability to breathe, and thoughts of self-harm (the reply adds 988).
- **Negation is understood:** "no chest pain, no swelling" raises nothing; "no dizziness but my ankles are swollen" raises the ankles.
- **Severity gating:** if the paper's 911 sign says "SEVERE trouble breathing" and the patient only says "a bit short of breath", the reply is
  "call your doctor today" plus "if it becomes severe or you cannot catch your breath, call 911".
- **Unclear never gets reassurance:** worrying wording that no rule recognises ("I feel really bad") becomes a **"please read"** alert for a person.
- **One event, one alert:** the paper's rule and the universal rule for the same symptom do not both fire; a weight gain over two windows is one alert.
- **Weights:** a number counts as a weight in the morning check-in, or when the message says weight / lb / kg. "My blood sugar is 150" is not saved as a weight.
- **Late answers work:** a "yes" sent after the next text arrived still marks the earlier reminder as taken.
- **STOP / START / HELP** are always honoured. After STOP nothing is sent.
- **Missed doses:** two reminders in a row not confirmed as taken raise one "please read" alert (not one per day).
- **A text that cannot be delivered** raises an alert instead of disappearing.
- **The first text** says texting is not for emergencies and how to stop.

## The files

| File | Role |
|---|---|
| `app/totals.py` | adds up acetaminophen over the whole schedule (tablet counts, `5/325` combinations, as-needed maximums) and warns above the paper's limit, else the common label maximum |
| `app/redflags.py` | symptom concepts, negation, rules from the paper, weight rules, yes/no parsing |
| `app/checkins.py` | the daily timeline, reminders, the morning check-in, reply handling, alerts, state for the screens |
| `app/store.py` | SQLite: patients, messages, alerts, weights, adherence |
| `app/sms.py` | Twilio sender, phone-number cleaning, webhook signature check |
| `components/FollowUpStep.tsx` | the phone simulator on the left, the care-team view on the right |

## Try the simulator (no accounts)

`./scripts/run-demo.sh`, upload a fictional paper, confirm, make the plan, then **Try it on the phone simulator**.
Press **Next text** to move through the day. Try: `172 and no symptoms`, then next day `176 and my ankles are swollen`, then `I have chest pain`.

## Reminder timer (real messages)

For **real messages** (Twilio texts or Telegram) a timer (`app/scheduler.py`) sends each reminder and the morning check-in by itself, at the right time **in the patient's own time zone**.
The phone simulator is still stepped by hand with "Next text".

- Every 30 seconds the server checks each real-text patient: which of today's texts are due and not yet sent? What was sent is remembered in the database, so a restart never repeats a text.
- Only texts that became due **after the patient signed up** are sent. Signing up at 3 PM does not fire the 8 AM reminder.
- **Late texts are skipped, not sent.** If the server was off and a reminder is more than 90 minutes late, it is not sent (a "take your medicine" text hours late can mislead). The care team gets a "please read" alert, so a missed reminder is never silent.
- The time zone comes from the browser when the patient signs up (`America/Chicago`...). If it is missing or invalid the server uses `MEDBRIDGE_TZ`, else `America/Los_Angeles`. Clock changes (daylight saving) keep 8:00 AM at 8:00 AM.
- Patients who replied STOP, or never agreed to texts, are never texted.
- One patient's error never stops everyone else's texts.
- The server must be **running** for texts to go out: if your laptop sleeps, reminders do not send. `MEDBRIDGE_SCHEDULER=off` turns the timer off.
- On a real patient's screen, "Send now (for testing)" sends the next text immediately, which is handy for a demo.

## Real messages on Telegram (free)

See "2a" in [setup-keys.md](setup-keys.md). The patient presses **Connect Telegram**, opens the link and presses Start; reminders, check-ins, replies, STOP and alerts then work exactly as in the simulator. A message Telegram refuses (for example the patient blocked the bot) is shown as **Not delivered** and raises a care-team alert.

## Real texts with Twilio

1. `./scripts/set-key.sh twilio` (Account SID, Auth Token, your Twilio number). It saves `.env` and tests the credentials.
2. Real replies need a public address. In another terminal: `ngrok http 8000` (or Cloudflare Tunnel). Copy the `https://....` address.
3. Put it in `.env` as `MEDBRIDGE_PUBLIC_URL=https://....` (no trailing slash), then restart the app with `./scripts/run-demo.sh --live`.
4. In the Twilio console: Phone Numbers > your number > Messaging > **A message comes in** > Webhook > `https://..../sms/incoming`, method POST.
5. On the plan screen, enter your own number (a trial account can only text numbers you verified), tick consent, press **Text my phone**.
6. Press **Next text** in the app to send the next reminder to your phone. Reply from your phone.

The webhook accepts only requests signed by Twilio (forged or unsigned ones get 403). The signature uses `MEDBRIDGE_PUBLIC_URL`, so it must match what Twilio calls.

## Limits (be honest in the demo)

- **No timer yet.** Reminders go out when someone presses **Next text** (or calls the API). A background scheduler with each patient's time zone is the next step for real use.
- **Texts are in English.** The plan can be translated, the texts cannot yet.
- **Keyword rules, not understanding.** Unusual wording can be missed. That is why unclear, worrying messages go to a person, but a calm-sounding message about a real problem could slip through. Never present this as a replacement for a nurse.
- **No login and no encryption.** Anyone who can reach the API can read a patient's data, and the SQLite file is plain. **Do not expose it to the internet or use real patient data** (Telegram messages are not private from Telegram or MedBridge's own server either) until accounts, encryption and a privacy agreement exist. (The Twilio webhook is signed; the other endpoints are not.)
- **SMS is not an emergency channel.** Carriers can delay or block texts. US trial numbers may be blocked entirely until registered (error 30034); use the simulator if that happens.
- **Units:** weights are in pounds (kilograms are converted).

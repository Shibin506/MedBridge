# Phase 6: polish, the demo, and what to say to judges

## What changed in this phase

- **Safety evaluation** (`backend/tests/test_safety_eval.py`): 336 labelled cases, realistic patient messages checked against all four
  sample papers. Writing it found real misses, now fixed: suicide wording ("I don't want to live anymore"), one-sided numbness or
  weakness, blue lips or fingertips, "cant breath", "I threw up blood", seizures, "worst headache of my life", and
  "I need 3 pillows to sleep". It also found two over-escalations: a paper's "bleeding that will not stop" turned *any* bleeding into
  "call 911", and "vomiting blood" turned any vomiting into "call 911". Warning signs are now judged clause by clause, keeping
  qualifiers such as "that will not stop" or "that lasts more than 48 hours".
- **Stated weight gains** ("I gained 4 pounds since yesterday") are checked against the paper's limits.
- **Accessibility:** axe-core found 0 WCAG 2 A/AA violations on all 10 screens checked (5 screens, light and dark). Fixed along the way:
  a keyboard-unreachable "Your paper" panel, low-contrast zero tiles, and a CSS clash that squashed exactly the cards a patient must check.
- **First screen** explains the product in three steps.
- **Demo video** (about 90 seconds, captions built in) and README screenshots.

## The demo video

[`docs/demo/medbridge-demo.mp4`](demo/medbridge-demo.mp4): recorded from the real app in demo mode (no keys needed), about 90 seconds,
following the same story as the live demo below with a caption on every step. It has no sound. To narrate it, read the captions aloud; they are written to be spoken.

## Live demo: 3 minutes

Start it with `./scripts/run-demo.sh` (demo mode: pre-written AI answers, so it works with no Wi-Fi or keys). Open http://localhost:3000.
Before going on stage: open **Care team** once and press **Remove the examples**, so the room sees them load fresh.

| Time | Click | Say |
|---|---|---|
| 0:00 | First screen | "After a hospital stay, people go home with pages of instructions. Studies of discharge communication find many patients cannot correctly name their own medicines or warning signs. MedBridge turns that paper into a plan they can follow, and keeps watching after they go home." |
| 0:20 | **Heart failure (fictional patient)** | "The AI reads the paper, but we never trust it blindly. Every item shows the exact words it came from." |
| 0:35 | Click **Potassium chloride** (yellow) | "This medicine is not in the paper. Our checker is plain code: it looked for the AI's quote in the document and did not find it. In demo mode we planted this on purpose." **Remove** it. |
| 0:55 | **This is right** on the rest, tick the boxes, **Make my plan** | "Nothing is used until a person confirms it." |
| 1:05 | Scroll the plan: Safety check, Stop taking, Your day | "A plain-language plan in 8 languages, a daily schedule, and safety checks done by code: duplicate ingredients, medicines the paper stopped, the daily acetaminophen limit, and interaction hints quoted from FDA labels." |
| 1:30 | Type a name, **Try it on the phone simulator**, **Next text**, **Yes, I took them**, **Next text** | "Every day, reminders and a morning check-in. Real messages go out on Telegram or SMS; here it is a pretend phone." |
| 1:50 | **176 and my ankles are swollen** | "Her own paper says to call the doctor for swelling, so that is exactly what she is told, and her care team is alerted. Code decides this, not an AI." |
| 2:05 | Type **I have chest pain**, **Send** | "Emergency words always get one answer: call 911 now." |
| 2:15 | **Care team**, **Load 6 example patients** | "The nurse sees every patient, worst first: emergencies, then call-today, then people who stopped answering their reminders." |
| 2:35 | **Mark as seen…** on the top alert, type a note, **Save as seen** | "Every alert keeps who handled it, when, and what they did." |
| 2:45 | Back to the first screen, or the README | "The AI reads, code verifies, people confirm. 804 automated tests, and none of the 156 emergency messages in our safety test set is missed." |

**If something breaks on stage:** demo mode needs no internet. If the page itself fails, play the video. If Telegram is part of
the plan, connect your phone *before* the talk (see docs/setup-keys.md, section 2a) and keep the simulator as the fallback.

## Questions judges are likely to ask

**"What if the AI makes something up?"**
It cannot get it into the plan. Every item must carry a quote that code finds in the paper, with the drug name and every number inside
that quote; anything else is flagged. Then the patient confirms each item. The plan's wording is checked again: same items, same
numbers, and "911" only where the paper says it. The planted fake medicine in the demo shows this working.

**"Who decides that a message is an emergency?"**
Code, from two sources: the warning signs in the patient's own confirmed paper, and a short fixed list that is always an emergency
(chest pain, fainting, stroke signs, blood when coughing or vomiting, a closing throat, blue lips, seizures, thoughts of self-harm).
Negation is understood ("no chest pain"), and vague worry ("I don't feel right") goes to a person instead of being reassured.

**"How do you know it works?"**
804 automated tests. The 336-case safety evaluation is the honest number: 156 emergency messages (39 phrasings × 4 papers), 0 missed;
96 calm messages, 0 false alarms; 60 vague-worry messages, all reach a person. It is our own test set, not a clinical validation:
the next step is a clinician reviewing the rules and a real-world message set.

**"Is it HIPAA compliant?"**
Not yet, and it says so. There are no accounts and no encryption of the local database; only fictional papers should be used.
Production needs accounts, encryption at rest, audit logs, a BAA with the AI and SMS providers, and a privacy review.

**"Why Telegram and not SMS?"**
Both are built. SMS (Twilio) is the right channel for most patients, but a US number must be registered with carriers first (days),
and Twilio's free trial only sends its own templates. Telegram works today, for free, and its replies need no public web address.

**"What does it cost to run?"**
The AI is only used to read the paper and reword the plan, a few calls per patient. Everything daily (reminders, checking replies,
alerts) is plain code, so it costs nothing per message apart from SMS fees.

## Known limits (say them before you are asked)

- The rules are not clinically validated, and the safety evaluation is our own message set.
- No accounts, no encryption, no BAA: fictional data only.
- Text and PDF input only; photos of paper discharge sheets need OCR.
- Interaction hints come only from text in FDA labels; "no hint" does not mean "safe" (the screen says so).
- The timer needs the server running; a laptop that sleeps sends nothing (missed reminders raise an alert when it wakes).

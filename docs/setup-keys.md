# Keys and accounts

Never paste a key into a chat, an issue, a commit or a screenshot. Keys live only in the `.env` file
(ignored by git) or in your hosting service's secret settings. If a key leaks, delete it and make a new one.

## 1. AI: Google Gemini (free tier)

1. Go to https://aistudio.google.com/apikey and sign in with a Google account.
2. Click **Create API key** and copy it.
3. In the project folder run `./scripts/set-key.sh`, paste the key when asked (nothing shows on screen), press Enter. It writes `.env` for you and tests the key. (Editing `.env` by hand also works: one line, `GEMINI_API_KEY=<key>`, no quotes or spaces.)
4. Run `./scripts/run-demo.sh --live`, then upload one of the **fictional** samples.

**Test the key before anything else:** `./scripts/check-key.sh`. It sends one tiny request to Google and tells you in
plain English whether the key works, is rate-limited, or needs fixing. It never prints the key (only its first 4
characters and its length). Keys from AI Studio start with `AIza`. Keys starting with `AQ.` are Google Cloud (Vertex)
keys; if the checker says yours only works that way, add `GEMINI_BACKEND=vertex` to `.env`.

Things to know:
- **Privacy:** on free tiers, Google may use submitted content to improve its products. Use only the fictional
  sample documents. Real patient papers need a paid/private setup and a data-processing agreement first.
- **Limits:** the free tier has per-minute and per-day request limits. If you hit them, MedBridge shows
  "The AI service is busy... try again". Waiting a minute usually fixes it.
- **Model names change.** The default is `gemini-2.5-flash`. If you see "does not know that model", set
  `MEDBRIDGE_MODEL=` in `.env` to a current model name from Google AI Studio.
- Claude still works: set `ANTHROPIC_API_KEY` instead (or `MEDBRIDGE_LLM=anthropic` to force it).

Quality check to do once: run `python scripts/try_extract.py samples/01_heart_failure.txt` (from `backend/`, with the
key in your environment) and look at how many items come back flagged. The checker flags any quote the AI
copied wrongly, which is a good measure of how well a given model follows the "copy exactly" rule.

## 2. SMS: Twilio (needed from Phase 4)

What Twilio calls things: you need the **Account SID**, the **Auth Token**, and **a phone number**. (Twilio also has
"API keys" starting with `SK`; we do not need those.)

1. Sign up at https://www.twilio.com/try-twilio (email + your mobile number; you get trial credit).
2. Verify your email and phone when asked.
3. Open the Console (https://console.twilio.com). The dashboard's **Account Info** box shows the **Account SID**
   (starts with `AC`) and the **Auth Token** (click to reveal).
4. Get a number: **Phone Numbers -> Manage -> Buy a number** (the trial credit pays for it). Choose one with SMS.
5. Trial accounts can only text numbers you have verified: **Phone Numbers -> Manage -> Verified Caller IDs ->
   Add a new caller ID**, and verify your own mobile.
6. Put these in `.env`:
   ```
   TWILIO_ACCOUNT_SID=AC...
   TWILIO_AUTH_TOKEN=...
   TWILIO_FROM_NUMBER=+1XXXXXXXXXX
   ```

Things to know:
- **Trial limits:** messages start with "Sent from your Twilio trial account" and go only to verified numbers.
- **US carrier registration:** US carriers block texts from unregistered ordinary numbers (Twilio error 30034/30032).
  Trial accounts may hit this. Twilio's toll-free verification or "A2P 10DLC" registration fixes it but takes days.
  Plan B for a hackathon: MedBridge will include an on-screen **SMS simulator**, so the demo never depends on carriers.
- **Receiving replies** needs a public web address that Twilio can call. On your laptop that means a tunnel tool such
  as ngrok or Cloudflare Tunnel. We will set that up in Phase 4.
- **Consent:** only text people who agreed to receive messages. Twilio handles STOP / HELP automatically.

# Keys and accounts

Never paste a key into a chat, an issue, a commit or a screenshot. Keys live only in the `.env` file
(ignored by git) or in your hosting service's secret settings. If a key leaks, delete it and make a new one.

## 1. AI: Groq (free tier, recommended)

1. Go to https://console.groq.com and sign up (free).
2. Open **API Keys** (https://console.groq.com/keys) and click **Create API Key**.
3. Click the **Copy** button. Groq shows the key only once. It starts with `gsk_`, and because it has no dots,
   double-clicking it also selects the whole key.
4. In the project folder run `./scripts/set-key.sh`, paste with Cmd+V (nothing shows on screen), and press Enter.
   It saves the key to `.env` and tests it with Groq. (Hand-editing also works: one line, `GROQ_API_KEY=<key>`.)
5. Run `./scripts/run-demo.sh --live` and upload one of the **fictional** samples.

Test the key any time with `./scripts/check-key.sh`. It never prints the key, only its first 4 characters and its length.

Things to know:
- **Privacy:** free hosted tiers may log or use what you send. Use only the fictional sample documents. For real
  patient papers you would need a paid or private setup first (or a model on your own computer, see below).
- **Limits:** the free tier has per-minute and per-day limits. If you hit them, MedBridge shows "The AI service is
  busy... try again". Waiting a minute usually fixes it.
- **Models change.** The default is `openai/gpt-oss-120b`. If Groq says the name is unknown, MedBridge lists the models
  your account can use and switches by itself (it logs the name to put in `.env` as `MEDBRIDGE_MODEL`).
- **Structured answers:** MedBridge asks for a strict schema first. If a model cannot do that, it falls back to plain
  JSON mode, and asks the model once to fix its own answer if the JSON is wrong. The checker still verifies every fact.
- **Other OpenAI-compatible services** (OpenRouter, Mistral, GitHub Models) and **Ollama on your own computer** (no key,
  nothing leaves your machine): set `MEDBRIDGE_LLM=openai_compat`, `LLM_BASE_URL=...` and `MEDBRIDGE_MODEL=...` in `.env`.

Quality check to do once: run `python scripts/try_extract.py samples/01_heart_failure.txt` (from `backend/`, with the
key in your environment) and look at how many items come back flagged. The checker flags any quote the AI copied
wrongly, which is a good measure of how well a given model follows the "copy exactly" rule.

## 1b. AI: Google Gemini (alternative)

1. Create a key at https://aistudio.google.com/apikey and use its **Copy** button (keys can start with `AIza` or `AQ.`;
   double-clicking stops at the dot and loses the start).
2. `./scripts/set-key.sh gemini`, then `./scripts/check-key.sh`. If the checker says the key only works as a Google Cloud
   (Vertex) key, add `GEMINI_BACKEND=vertex` to `.env`. `./scripts/check-key.sh --fix` repairs a key that lost its `AQ.` start.
3. To use Gemini when a Groq key is also saved, set `MEDBRIDGE_LLM=gemini` in `.env`.

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

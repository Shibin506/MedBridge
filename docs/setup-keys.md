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

## 2a. Free phone messages: a Telegram bot (no carrier approval, no trial limits)

Twilio's free trial only allows its own ready-made templates, and US carriers block new numbers for days. A Telegram bot has neither problem, costs nothing,
and needs no public web address. The patient needs the free Telegram app. (Twilio SMS stays in MedBridge for real deployments.)

1. In Telegram, search for **@BotFather** (the one with the blue check) and send `/newbot`.
2. Give it a name (for example `MedBridge Demo`) and a username that ends in `bot` (for example `medbridge_demo_bot`).
3. BotFather replies with a token like `123456789:ABC...`. Treat it like a password.
4. In the MedBridge folder run `./scripts/set-key.sh telegram`, paste the token (nothing shows), press Enter. It saves `.env` and tests it.
5. Test any time with `./scripts/check-key.sh telegram`.
6. Start MedBridge (`./scripts/run-demo.sh`), make a plan, press **Connect Telegram**, open the link on your phone and press **Start**.

How it works: the link carries a one-time secret; pressing Start tells MedBridge which Telegram chat is the patient (and counts as agreeing to messages).
MedBridge asks Telegram for new messages every few seconds, so nothing needs to be reachable from the internet. Only **one** copy of MedBridge can read the bot's
messages at a time (a second one gets error 409). Messages are plain text and are sent at the same times as the SMS ones.

## 2. Text messages: Twilio (for real texts; the phone simulator needs none of this)

What Twilio calls things: the **Account SID** (starts with `AC`), the **Auth Token**, and **a phone number**. (Twilio "API keys" starting with `SK` are not needed.)

1. Sign up at https://www.twilio.com/try-twilio (email and your mobile number; you get trial credit) and verify both.
2. In the Console (https://console.twilio.com), **Account Info** shows the Account SID and Auth Token (click to reveal).
3. Get a number: **Phone Numbers > Manage > Buy a number** (trial credit pays for it), one with SMS.
4. Trial accounts can only text numbers you verified: **Phone Numbers > Manage > Verified Caller IDs > Add**, and verify your own mobile.
5. In the project folder run `./scripts/set-key.sh twilio` and paste the three values. It saves `.env` and tests them (including that the number is in your account).
6. Test any time with `./scripts/check-key.sh twilio`.
7. For replies to reach the app, follow "Real texts with Twilio" in [phase-4.md](phase-4.md) (a tunnel such as `ngrok http 8000`, `MEDBRIDGE_PUBLIC_URL`, and the webhook address).

Things to know:
- **Trial limits:** messages go only to verified numbers, and (since Twilio's 2026 trial rules) a trial account can only send Twilio's **ready-made templates**,
  not your own wording. MedBridge's reminders are its own wording, so real texts need the account **upgraded** (error 572006 means this). The phone simulator needs nothing.
- **US carrier registration:** US carriers block texts from unregistered ordinary numbers (Twilio errors 30034 / 30032).
  Trial accounts may hit this. Twilio's toll-free verification or A2P 10DLC registration fixes it but takes days.
  For a hackathon, the **phone simulator** means the demo never depends on carriers.
- **Consent:** only text people who agreed. Twilio handles STOP / HELP automatically, and MedBridge honours them too.

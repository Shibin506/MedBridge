"""Test a Gemini key against Google and say what to do. Never prints the key."""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

from .llm import (
    GEMINI_DEFAULT_MODEL,
    GROQ_BASE_URL,
    GROQ_DEFAULT_MODEL,
    GROQ_PREFERRED,
    GeminiClient,
    pick_chat_model,
    selected_provider,
)


@dataclass
class Attempt:
    name: str  # "AI Studio" or "Vertex express"
    ok: bool
    code: int | None = None
    note: str = ""  # short reason, key removed
    model_used: str | None = None  # set when the asked-for model did not exist and another one worked


def advise(key: str, studio: Attempt, vertex: Attempt) -> list[str]:
    """Plain-English next steps from the two test results."""
    shape = f"Your key starts with “{key[:4]}” and is {len(key)} characters long."
    if studio.ok:
        lines = [shape, "PASS: Google AI Studio accepted the key."]
        if studio.model_used:
            lines += [f"Note: the model name we asked for does not exist for your key; “{studio.model_used}” works.",
                      f"The app switches to it by itself. To make it permanent, add this line to .env:  MEDBRIDGE_MODEL={studio.model_used}"]
        return lines + ["Nothing else to change. Run ./scripts/run-demo.sh --live."]
    if studio.code == 429:
        return [shape, "The key is VALID but its free limit is used up right now.", "Wait a minute (or until tomorrow) and try again."]
    if vertex.ok or vertex.code == 429:
        return [shape, "This key does NOT work with AI Studio, but it DOES work as a Google Cloud (Vertex) key.",
                "Fix: add this line to your .env file (below the key line), save, and run ./scripts/run-demo.sh --live:",
                "    GEMINI_BACKEND=vertex",
                "Or, to use the free AI Studio instead, create a key at https://aistudio.google.com/apikey (starts with AIza)."]
    lines = [shape, "FAIL: Google rejected the key in both places."]
    if not key.startswith(("AIza", "AQ.")):
        lines += [
            "",
            "!! Your key does not start with AIza or AQ.  It may have lost its first characters when it was copied.",
            "   Double-clicking a key stops at the first dot, so a key like “AQ.xxxx…” loses its “AQ.” part.",
            "   Use the COPY button next to the key in Google's page (or click and drag over the whole key),",
            "   and check that the pasted line in .env starts with AIza or AQ.",
            "",
        ]
    if studio.code == 404 or vertex.code == 404:
        lines.append(f"One service says the model name is unknown. Set MEDBRIDGE_MODEL in .env to a current model name.")
    else:
        lines += [
            "Most likely the key was deleted, mistyped, or copied with a missing part.",
            "1. Open https://aistudio.google.com/apikey and click “Create API key”.",
            "2. Copy the WHOLE key (it usually starts with AIza and is about 39 characters).",
            "3. In .env, make the line exactly:  GEMINI_API_KEY=<the key>   (nothing else on the line).",
            "4. Run ./scripts/check-key.sh again.",
        ]
    lines.append(f"(AI Studio said: {studio.note or studio.code}; Vertex said: {vertex.note or vertex.code})")
    return lines


def _try(name: str, key: str, model: str, vertex: bool) -> Attempt:
    from google import genai
    from google.genai import errors, types

    try:
        client = genai.Client(vertexai=True, api_key=key) if vertex else genai.Client(api_key=key)
        cfg = types.GenerateContentConfig(automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True))
        try:
            client.models.generate_content(model=model, contents="Reply with the single word OK.", config=cfg)
            return Attempt(name, True)
        except errors.APIError as exc:
            # The key was accepted but the model name is unknown (retired?): find one this key can use.
            alt = GeminiClient(api_key=key, client=client)._discover(model) if getattr(exc, "code", None) == 404 else None
            if not alt:
                raise
            client.models.generate_content(model=alt, contents="Reply with the single word OK.", config=cfg)
            return Attempt(name, True, model_used=alt)
    except errors.APIError as exc:
        text = str(getattr(exc, "message", "") or exc).replace(key, "<key>")
        return Attempt(name, False, getattr(exc, "code", None), " ".join(text.split())[:140])
    except Exception as exc:  # no internet, DNS, timeout
        return Attempt(name, False, None, f"could not reach Google ({type(exc).__name__})")


def groq_advise(key: str, status: int | None, model_ids: list[str], model: str) -> list[str]:
    """Plain-English next steps from Groq's answer to 'list my models'."""
    shape = f"Your key starts with “{key[:4]}” and is {len(key)} characters long."
    if status == 200:
        lines = [shape, "PASS: Groq accepted the key."]
        if model_ids and model not in model_ids:
            alt = pick_chat_model(model_ids, GROQ_PREFERRED)
            lines += [f"Note: the model “{model}” is not available to your account; the app will use “{alt}” by itself.",
                      f"To make it permanent, add this line to .env:  MEDBRIDGE_MODEL={alt}"]
        return lines + ["Nothing else to change. Run ./scripts/run-demo.sh --live."]
    if status == 429:
        return [shape, "The key is VALID but you have used up Groq's free limit for now.", "Wait a minute and try again."]
    if status in (401, 403):
        lines = [shape, "FAIL: Groq rejected the key."]
        if not key.startswith("gsk_"):
            lines += ["!! Groq keys start with gsk_ and yours does not. It may be a different kind of key, or part of it was cut off."]
        return lines + ["1. Open https://console.groq.com/keys and click “Create API Key”.",
                        "2. Click the Copy button (Groq shows the key only once).",
                        "3. Run ./scripts/set-key.sh and paste it (Cmd+V), then press Enter."]
    if status is None:
        return [shape, "Could not reach Groq. Check your internet connection and try again."]
    return [shape, f"Groq answered with an unexpected error ({status}). Try again in a minute."]


def twilio_advise(status: int | None, account: dict, number_found: bool | None, from_number: str) -> list[str]:
    """Plain-English result of testing the Twilio credentials. ``number_found`` is None when it could not be checked."""
    if status is None:
        return ["Could not reach Twilio. Check your internet connection and try again."]
    if status in (401, 403):
        return ["FAIL: Twilio rejected the Account SID / Auth Token.",
                "1. Open https://console.twilio.com and find “Account Info”.",
                "2. Copy the Account SID (starts with AC) and the Auth Token (click to show it).",
                "3. Run ./scripts/set-key.sh twilio and paste them."]
    if status != 200:
        return [f"Twilio answered with an unexpected error ({status}). Try again in a minute."]
    kind = (account.get("type") or "").lower()
    lines = ["PASS: Twilio accepted your Account SID and Auth Token."]
    if account.get("status") and account["status"] != "active":
        lines.append(f"!! Your Twilio account status is “{account['status']}”. Texts will not send until it is active.")
    if number_found is False:
        lines += [f"!! The number {from_number} is not in this Twilio account. Check TWILIO_FROM_NUMBER, or buy a number at",
                  "   Console > Phone Numbers > Manage > Buy a number."]
    elif number_found:
        lines.append(f"The number {from_number} belongs to your account.")
    if kind == "trial":
        lines += ["This is a TRIAL account: it can only text phone numbers you have verified",
                  "(Console > Phone Numbers > Manage > Verified Caller IDs), and messages start with a trial notice.",
                  "US carriers may also block texts from a new number until it is registered (Twilio error 30034).",
                  "If texts do not arrive, use the phone simulator for your demo."]
    lines.append("Next: for REPLIES to reach the app, set up the webhook (see docs/setup-keys.md).")
    return lines


def run_twilio() -> int:
    sid, token, number = (os.environ.get(k, "").strip() for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM_NUMBER"))
    if not (sid and token and number):
        print("Twilio is not set up. Run ./scripts/set-key.sh twilio and paste the three values.")
        return 2
    print(f"Testing Twilio (account starts with “{sid[:4]}”, auth token {len(token)} characters)...")
    base = f"https://api.twilio.com/2010-04-01/Accounts/{sid}"
    try:
        r = httpx.get(base + ".json", auth=(sid, token), timeout=20)
        status, account = r.status_code, (r.json() if r.status_code == 200 else {})
        found = None
        if status == 200:
            n = httpx.get(base + "/IncomingPhoneNumbers.json", params={"PhoneNumber": number}, auth=(sid, token), timeout=20)
            found = bool(n.json().get("incoming_phone_numbers")) if n.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        status, account, found = None, {}, None
    print()
    print("\n".join(twilio_advise(status, account, found, number)))
    return 0 if status == 200 else 1


def run_groq() -> int:
    key = os.environ.get("GROQ_API_KEY", "").strip()
    if not key:
        print("No Groq key found. Run ./scripts/set-key.sh and paste your key.")
        return 2
    model = os.environ.get("MEDBRIDGE_MODEL") or GROQ_DEFAULT_MODEL
    print(f"Testing the Groq key (listing the models your account can use)...")
    try:
        r = httpx.get(GROQ_BASE_URL + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
        status, ids = r.status_code, ([m.get("id", "") for m in r.json().get("data", [])] if r.status_code == 200 else [])
    except (httpx.HTTPError, ValueError):
        status, ids = None, []
    print()
    print("\n".join(groq_advise(key, status, ids, model)))
    return 0 if status in (200, 429) else 1


LOST_PREFIX = "AQ."
KEY_LENGTH_WITHOUT_PREFIX = 50  # keys that start with AQ. are 53 characters long in total


def write_key(env_path: Path, key: str, vertex: bool) -> None:
    """Replace the key (and backend) lines in .env, keeping every other line. Never prints the key."""
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    lines = [l for l in lines if not l.startswith(("GEMINI_API_KEY=", "GEMINI_BACKEND="))]
    head = [f"GEMINI_API_KEY={key}"] + (["GEMINI_BACKEND=vertex"] if vertex else [])
    env_path.write_text("\n".join(head + lines) + "\n")
    env_path.chmod(0o600)


def try_restoring_prefix(key: str, model: str) -> tuple[str, bool] | None:
    """If the key looks like it lost its “AQ.” start, test the repaired key. Returns (repaired_key, needs_vertex)."""
    if key.startswith(("AIza", LOST_PREFIX)) or len(key) != KEY_LENGTH_WITHOUT_PREFIX:
        return None
    repaired = LOST_PREFIX + key
    studio = _try("AI Studio", repaired, model, vertex=False)
    if studio.ok or studio.code == 429:
        return repaired, False
    vertex = _try("Vertex express", repaired, model, vertex=True)
    if vertex.ok or vertex.code == 429:
        return repaired, True
    return None


def run(fix: bool = False, twilio: bool = False) -> int:
    if twilio:
        return run_twilio()
    if selected_provider() == "groq":
        return run_groq()
    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if not key:
        print("No key found. Copy .env.example to .env and put your key after GEMINI_API_KEY=")
        return 2
    model = os.environ.get("MEDBRIDGE_MODEL") or GEMINI_DEFAULT_MODEL
    print(f"Testing the key with model {model} (a tiny request)...")
    studio = _try("AI Studio", key, model, vertex=False)
    vertex = Attempt("Vertex express", False, None, "skipped") if studio.ok else _try("Vertex express", key, model, vertex=True)
    print()
    print("\n".join(advise(key, studio, vertex)))
    if studio.ok or studio.code == 429 or vertex.ok or vertex.code == 429:
        return 0

    found = try_restoring_prefix(key, model)
    if found is None:
        return 1
    repaired, vertex_needed = found
    print()
    print("FOUND IT: your key works once the missing “AQ.” is put back at the start.")
    if not fix:
        print("Run this to repair .env automatically (it only saves a key that Google has just accepted):")
        print("    ./scripts/check-key.sh --fix")
        return 1
    env_path = Path(os.environ.get("MEDBRIDGE_ENV_FILE") or Path(__file__).resolve().parents[2] / ".env")
    write_key(env_path, repaired, vertex_needed)
    print(f"Repaired .env (key is now {len(repaired)} characters" + (", GEMINI_BACKEND=vertex added" if vertex_needed else "") + ").")
    print("Run ./scripts/run-demo.sh --live. Since this key was shared in a chat, replace it with a fresh one after your testing.")
    return 0

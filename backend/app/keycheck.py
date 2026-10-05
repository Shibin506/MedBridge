"""Test a Gemini key against Google and say what to do. Never prints the key."""

import os
from dataclasses import dataclass

from .llm import GEMINI_DEFAULT_MODEL


@dataclass
class Attempt:
    name: str  # "AI Studio" or "Vertex express"
    ok: bool
    code: int | None = None
    note: str = ""  # short reason, key removed


def advise(key: str, studio: Attempt, vertex: Attempt) -> list[str]:
    """Plain-English next steps from the two test results."""
    shape = f"Your key starts with “{key[:4]}” and is {len(key)} characters long."
    if studio.ok:
        return [shape, "PASS: Google AI Studio accepted the key.", "Nothing to change. Run ./scripts/run-demo.sh --live."]
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
        client.models.generate_content(
            model=model, contents="Reply with the single word OK.",
            config=types.GenerateContentConfig(automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)),
        )
        return Attempt(name, True)
    except errors.APIError as exc:
        text = str(getattr(exc, "message", "") or exc).replace(key, "<key>")
        return Attempt(name, False, getattr(exc, "code", None), " ".join(text.split())[:140])
    except Exception as exc:  # no internet, DNS, timeout
        return Attempt(name, False, None, f"could not reach Google ({type(exc).__name__})")


def run() -> int:
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
    return 0 if (studio.ok or studio.code == 429 or vertex.ok or vertex.code == 429) else 1

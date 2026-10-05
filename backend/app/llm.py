"""Which AI service answers: Google Gemini (free tier) or Anthropic Claude.

The rest of the app talks to ONE tiny interface:

    client.messages.parse(model=..., max_tokens=..., system=..., messages=[...], output_format=PydanticModel)
        -> object with .parsed_output (a PydanticModel instance, or None) and .stop_reason

``anthropic.Anthropic().messages.parse`` already has this shape. ``GeminiClient`` below gives Gemini the
same shape, so Extractor / PlanGenerator (and all their tests) do not care which provider is behind it.

Choosing a provider (first match wins):
  MEDBRIDGE_LLM=gemini|anthropic   explicit
  GEMINI_API_KEY (or GOOGLE_API_KEY) set   -> Gemini
  ANTHROPIC_API_KEY set                    -> Claude
"""

import logging
import os
import re
from types import SimpleNamespace
from typing import Any

from pydantic import ValidationError

# "-latest" is Google's moving alias for the newest Flash model, so a retired version name cannot break us.
# If even that name is unknown, the client asks Google which models this key can use and picks one (see pick_model).
GEMINI_DEFAULT_MODEL = "gemini-flash-latest"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_MODEL = GEMINI_DEFAULT_MODEL

log = logging.getLogger("uvicorn.error")

NO_KEY_MESSAGE = (
    "No AI key found. Get a free Gemini key at https://aistudio.google.com/apikey, then put "
    "GEMINI_API_KEY=your-key in the .env file in the project folder (see .env.example)."
)


class LLMError(RuntimeError):
    """The AI service answered, but not with something we can use."""


class LLMUnavailable(LLMError):
    """The AI service is busy, rate-limited or unreachable. Trying again later may work."""


_SKIP = ("image", "tts", "live", "audio", "embedding", "native", "robotics", "computer", "imagen", "veo", "learnlm")


def pick_model(models: list, exclude: str | None = None) -> str | None:
    """Choose the best general-purpose Flash model from Google's list: stable over preview, full over lite, newest first."""
    best, best_key = None, None
    for m in models:
        short = (getattr(m, "name", "") or "").removeprefix("models/")
        low = short.lower()
        if short == exclude or "flash" not in low or any(x in low for x in _SKIP):
            continue
        if "generateContent" not in (getattr(m, "supported_actions", None) or []):
            continue
        version = re.search(r"(\d+(?:\.\d+)?)", low)
        key = (not any(x in low for x in ("preview", "exp")), "lite" not in low, float(version.group(1)) if version else 0.0)
        if best_key is None or key > best_key:
            best, best_key = short, key
    return best


def _friendly(code: int | None, raw: str) -> str:
    low = raw.lower()
    if "api key" in low or code in (401, 403):
        return ("Gemini rejected the API key. Check GEMINI_API_KEY in your .env file: no spaces or quotes, "
                "and a key created at https://aistudio.google.com/apikey. Run ./scripts/check-key.sh to test the key.")
    if code == 404 or "not found" in low:
        return ("Gemini does not know that model name. Set MEDBRIDGE_MODEL in .env to a current model "
                "listed at https://aistudio.google.com.")
    return f"Gemini returned an error ({code}): {raw[:300]}"


class GeminiClient:
    default_model = GEMINI_DEFAULT_MODEL

    def __init__(self, api_key: str | None = None, client: Any | None = None, vertex: bool = False):
        self._api_key = api_key
        self._vertex = vertex  # True for the other kind of Google key (Google Cloud "Vertex AI express mode", starts with AQ.)
        self._client = client  # injectable for tests
        self._resolved: dict[str, str] = {}  # asked-for model -> model we switched to
        self.messages = SimpleNamespace(parse=self._parse)

    @property
    def client(self) -> Any:
        if self._client is None:
            from google import genai  # imported lazily so the app starts without the package in demo mode

            self._client = genai.Client(vertexai=True, api_key=self._api_key) if self._vertex else genai.Client(api_key=self._api_key)
        return self._client

    def _discover(self, current: str) -> str | None:
        try:
            return pick_model(list(self.client.models.list()), exclude=current)
        except Exception:
            return None

    def _parse(self, *, model: str, max_tokens: int, system: str, messages: list[dict], output_format: Any, **_ignored):
        from google.genai import errors, types

        contents = "\n\n".join(m["content"] for m in messages if m.get("role") == "user")
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=output_format,  # a Pydantic model class: Gemini must answer in exactly this shape
            max_output_tokens=max_tokens,
            # We never use tool calling; this also silences a noisy (harmless) library warning.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        current = self._resolved.get(model, model)
        for attempt in range(2):
            try:
                response = self.client.models.generate_content(model=current, contents=contents, config=config)
                break
            except errors.APIError as exc:
                code = getattr(exc, "code", None)
                if code == 404 and attempt == 0 and (alt := self._discover(current)):
                    # The model name is retired or unknown: use one this key can really use, once.
                    log.warning("Gemini model %s is not available; switching to %s. Set MEDBRIDGE_MODEL=%s to make it permanent.",
                                current, alt, alt)
                    self._resolved[model] = current = alt
                    continue
                if code in (429, 500, 502, 503, 504):
                    raise LLMUnavailable(f"Gemini is busy or rate-limited (error {code}).") from exc
                raise LLMError(_friendly(code, str(exc))) from exc
            except Exception as exc:  # network trouble, timeouts, DNS
                raise LLMUnavailable(f"Could not reach Gemini: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        problem = None
        if not isinstance(parsed, output_format):
            parsed = None
            text = getattr(response, "text", None) or ""
            if not text.strip():
                problem = "empty answer"
            else:
                try:
                    parsed = output_format.model_validate_json(text)
                except ValidationError as exc:
                    # Where it went wrong, never the content (it could contain patient details).
                    bad = sorted({".".join(str(p) for p in e["loc"][:3]) + f" ({e['type']})" for e in exc.errors(include_input=False)})
                    problem = "answer did not match the expected shape: " + "; ".join(bad[:4])
                except Exception:
                    problem = "answer was not valid JSON"
        finish = None
        if getattr(response, "candidates", None):
            finish = str(getattr(response.candidates[0], "finish_reason", None))
        return SimpleNamespace(parsed_output=parsed, stop_reason="; ".join(x for x in (finish, problem) if x) or None)


class AnthropicClient:
    default_model = ANTHROPIC_DEFAULT_MODEL

    def __init__(self):
        import anthropic

        self.messages = anthropic.Anthropic().messages


def make_client(provider: str | None = None) -> Any:
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    provider = (provider or os.environ.get("MEDBRIDGE_LLM") or "").lower()
    if not provider:
        provider = "gemini" if gemini_key else ("anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "")
    if provider == "gemini":
        if not gemini_key:
            raise LLMError(NO_KEY_MESSAGE)
        return GeminiClient(api_key=gemini_key, vertex=os.environ.get("GEMINI_BACKEND", "").lower() == "vertex")
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("MEDBRIDGE_LLM=anthropic but ANTHROPIC_API_KEY is not set.")
        return AnthropicClient()
    raise LLMError(NO_KEY_MESSAGE)


def model_for(client: Any, explicit: str | None) -> str:
    """Explicit argument > MEDBRIDGE_MODEL env var > the provider's default."""
    return explicit or os.environ.get("MEDBRIDGE_MODEL") or getattr(client, "default_model", FALLBACK_MODEL)

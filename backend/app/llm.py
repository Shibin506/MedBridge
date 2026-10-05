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

import os
from types import SimpleNamespace
from typing import Any

GEMINI_DEFAULT_MODEL = "gemini-2.5-flash"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_MODEL = GEMINI_DEFAULT_MODEL

NO_KEY_MESSAGE = (
    "No AI key found. Get a free Gemini key at https://aistudio.google.com/apikey, then put "
    "GEMINI_API_KEY=your-key in the .env file in the project folder (see .env.example)."
)


class LLMError(RuntimeError):
    """The AI service answered, but not with something we can use."""


class LLMUnavailable(LLMError):
    """The AI service is busy, rate-limited or unreachable. Trying again later may work."""


def _friendly(code: int | None, raw: str) -> str:
    low = raw.lower()
    if "api key" in low or code in (401, 403):
        return ("Gemini rejected the API key. Check GEMINI_API_KEY in your .env file: no spaces or quotes, "
                "and a key created at https://aistudio.google.com/apikey.")
    if code == 404 or "not found" in low:
        return ("Gemini does not know that model name. Set MEDBRIDGE_MODEL in .env to a current model "
                "listed at https://aistudio.google.com.")
    return f"Gemini returned an error ({code}): {raw[:300]}"


class GeminiClient:
    default_model = GEMINI_DEFAULT_MODEL

    def __init__(self, api_key: str | None = None, client: Any | None = None):
        self._api_key = api_key
        self._client = client  # injectable for tests
        self.messages = SimpleNamespace(parse=self._parse)

    @property
    def client(self) -> Any:
        if self._client is None:
            from google import genai  # imported lazily so the app starts without the package in demo mode

            self._client = genai.Client(api_key=self._api_key)
        return self._client

    def _parse(self, *, model: str, max_tokens: int, system: str, messages: list[dict], output_format: Any, **_ignored):
        from google.genai import errors, types

        contents = "\n\n".join(m["content"] for m in messages if m.get("role") == "user")
        config = types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=output_format,  # a Pydantic model class: Gemini must answer in exactly this shape
            max_output_tokens=max_tokens,
        )
        try:
            response = self.client.models.generate_content(model=model, contents=contents, config=config)
        except errors.APIError as exc:
            code = getattr(exc, "code", None)
            if code in (429, 500, 502, 503, 504):
                raise LLMUnavailable(f"Gemini is busy or rate-limited (error {code}).") from exc
            raise LLMError(_friendly(code, str(exc))) from exc
        except Exception as exc:  # network trouble, timeouts, DNS
            raise LLMUnavailable(f"Could not reach Gemini: {exc}") from exc

        parsed = getattr(response, "parsed", None)
        if not isinstance(parsed, output_format):
            try:
                parsed = output_format.model_validate_json(getattr(response, "text", None) or "")
            except Exception:
                parsed = None
        finish = None
        if getattr(response, "candidates", None):
            finish = str(getattr(response.candidates[0], "finish_reason", None))
        return SimpleNamespace(parsed_output=parsed, stop_reason=finish)


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
        return GeminiClient(api_key=gemini_key)
    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("MEDBRIDGE_LLM=anthropic but ANTHROPIC_API_KEY is not set.")
        return AnthropicClient()
    raise LLMError(NO_KEY_MESSAGE)


def model_for(client: Any, explicit: str | None) -> str:
    """Explicit argument > MEDBRIDGE_MODEL env var > the provider's default."""
    return explicit or os.environ.get("MEDBRIDGE_MODEL") or getattr(client, "default_model", FALLBACK_MODEL)

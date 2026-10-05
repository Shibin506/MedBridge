"""Which AI service answers: Google Gemini (free tier) or Anthropic Claude.

The rest of the app talks to ONE tiny interface:

    client.messages.parse(model=..., max_tokens=..., system=..., messages=[...], output_format=PydanticModel)
        -> object with .parsed_output (a PydanticModel instance, or None) and .stop_reason

``anthropic.Anthropic().messages.parse`` already has this shape. ``GeminiClient`` below gives Gemini the
same shape, so Extractor / PlanGenerator (and all their tests) do not care which provider is behind it.

Choosing a provider (first match wins):
  MEDBRIDGE_LLM=groq|gemini|anthropic|openai_compat   explicit
  GROQ_API_KEY set                         -> Groq (free tier)
  GEMINI_API_KEY (or GOOGLE_API_KEY) set   -> Gemini
  ANTHROPIC_API_KEY set                    -> Claude
"""

import json
import logging
import os
import re
from types import SimpleNamespace
from typing import Any

import httpx
from pydantic import ValidationError

# "-latest" is Google's moving alias for the newest Flash model, so a retired version name cannot break us.
# If even that name is unknown, the client asks Google which models this key can use and picks one (see pick_model).
GEMINI_DEFAULT_MODEL = "gemini-flash-latest"
ANTHROPIC_DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_MODEL = GEMINI_DEFAULT_MODEL

log = logging.getLogger("uvicorn.error")

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_DEFAULT_MODEL = "openai/gpt-oss-120b"
# If the model above is gone, pick the first of these that the account can use (models change often).
GROQ_PREFERRED = (
    "openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile",
    "meta-llama/llama-4-maverick-17b-128e-instruct", "meta-llama/llama-4-scout-17b-16e-instruct",
    "qwen/qwen3-32b", "moonshotai/kimi-k2-instruct",
)
_NOT_CHAT = ("whisper", "guard", "tts", "orpheus", "playai", "embed", "safeguard", "transcribe")
MAX_OUTPUT_TOKENS = 6000  # free tiers limit tokens per minute; our answers are well under this

NO_KEY_MESSAGE = (
    "No AI key found. Get a free Groq key at https://console.groq.com/keys, then run ./scripts/set-key.sh and paste it "
    "(or use a free Gemini key from https://aistudio.google.com/apikey and run ./scripts/set-key.sh gemini)."
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


def strict_schema(schema: dict) -> dict:
    """Pydantic's JSON schema -> the stricter form structured-output APIs ask for:
    every object is closed (no extra fields) and every property is listed as required."""

    def walk(node):
        if isinstance(node, list):
            return [walk(x) for x in node]
        if not isinstance(node, dict):
            return node
        out = {}
        for key, value in node.items():
            if key in ("properties", "$defs", "definitions") and isinstance(value, dict):
                out[key] = {name: walk(sub) for name, sub in value.items()}  # field names are not schema keywords
            else:
                out[key] = walk(value)
        if "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out

    return walk(schema)


def pick_chat_model(model_ids: list[str], preferred: tuple[str, ...], exclude: str | None = None) -> str | None:
    ids = [m for m in model_ids if m != exclude and not any(x in m.lower() for x in _NOT_CHAT)]
    for name in preferred:
        if name in ids:
            return name
    return ids[0] if ids else None


class _ModelNotFound(Exception):
    pass


class _BadRequest(Exception):
    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


_FORMAT_PROBLEM = re.compile(r"response_format|json_schema|structured|schema|does not support|not supported", re.I)
_SCHEMA_HINT = (
    "\n\nReply with ONE JSON object and nothing else. It must match this JSON Schema exactly "
    "(use null for unknown values, never invent fields):\n"
)


def _extract_json(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    if not text.startswith("{") and "{" in text and "}" in text:
        text = text[text.index("{"): text.rindex("}") + 1]
    return text


class OpenAICompatClient:
    """Talks the common "OpenAI-compatible" chat format that Groq, OpenRouter, Mistral, GitHub Models and Ollama share.

    Models differ in how well they obey a schema, so it tries the strict way first (response_format=json_schema),
    falls back to plain JSON mode with the schema written into the prompt if the model refuses that, and asks the
    model once to fix its own answer if the JSON does not match. Our checker (verify.py) still checks every fact.
    """

    def __init__(self, api_key: str, base_url: str, default_model: str, name: str = "Groq",
                 preferred: tuple[str, ...] = GROQ_PREFERRED, client: httpx.Client | None = None):
        self.default_model = default_model
        self._name, self._key, self._base, self._preferred = name, api_key, base_url.rstrip("/"), preferred
        self._http = client  # injectable for tests
        self._mode = "json_schema"
        self._resolved: dict[str, str] = {}
        self.messages = SimpleNamespace(parse=self._parse)

    @property
    def http(self) -> httpx.Client:
        if self._http is None:
            self._http = httpx.Client(timeout=90)
        return self._http

    # ---- HTTP -------------------------------------------------------
    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        try:
            r = self.http.request(method, self._base + path, json=body,
                                  headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Could not reach {self._name}: {type(exc).__name__}") from exc
        if r.status_code == 200:
            try:
                return r.json()
            except ValueError as exc:
                raise LLMError(f"{self._name} sent a reply that is not JSON.") from exc
        text = " ".join(r.text.split())[:300].replace(self._key, "<key>")
        if r.status_code in (401, 403):
            raise LLMError(f"{self._name} rejected the API key. Run ./scripts/set-key.sh and paste a fresh key "
                           f"(Groq keys start with gsk_). Then ./scripts/check-key.sh tests it.")
        if r.status_code == 404:
            raise _ModelNotFound(text)
        if r.status_code == 400:
            raise _BadRequest(text)
        if r.status_code == 413:
            raise LLMError(f"The request is too big for this model's free limit ({text}). Try another model via MEDBRIDGE_MODEL.")
        if r.status_code in (408, 429, 500, 502, 503, 504):
            raise LLMUnavailable(f"{self._name} is busy or rate-limited (error {r.status_code}).")
        raise LLMError(f"{self._name} returned an error ({r.status_code}): {text}")

    def list_models(self) -> list[str]:
        return [m["id"] for m in self._request("GET", "/models").get("data", []) if "id" in m]

    def _discover(self, current: str) -> str | None:
        try:
            return pick_chat_model(self.list_models(), self._preferred, exclude=current)
        except Exception:
            return None

    # ---- the one call the rest of the app uses ----------------------
    def _body(self, model, max_tokens, system, messages, output_format, extra):
        schema = output_format.model_json_schema()
        if self._mode == "json_schema":
            sys_text = system
            fmt = {"type": "json_schema", "json_schema": {"name": output_format.__name__, "strict": True,
                                                        "schema": strict_schema(schema)}}
        else:
            sys_text = system + _SCHEMA_HINT + json.dumps(schema)
            fmt = {"type": "json_object"}
        return {"model": model, "temperature": 0, "max_tokens": min(max_tokens, MAX_OUTPUT_TOKENS),
                "response_format": fmt, "messages": [{"role": "system", "content": sys_text}, *messages, *extra]}

    @staticmethod
    def _validate(content: str, output_format):
        if not content.strip():
            return None, "empty answer"
        try:
            return output_format.model_validate_json(_extract_json(content)), None
        except ValidationError as exc:
            bad = sorted({".".join(str(p) for p in e["loc"][:3]) + f" ({e['type']})" for e in exc.errors(include_input=False)})
            return None, "answer did not match the expected shape: " + "; ".join(bad[:4])
        except Exception:
            return None, "answer was not valid JSON"

    def _parse(self, *, model: str, max_tokens: int, system: str, messages: list[dict], output_format: Any, **_ignored):
        current = self._resolved.get(model, model)
        extra: list[dict] = []
        swapped = repaired = False
        for _ in range(5):
            try:
                data = self._request("POST", "/chat/completions",
                                     self._body(current, max_tokens, system, messages, output_format, extra))
            except _ModelNotFound as exc:
                alt = None if swapped else self._discover(current)
                if not alt:
                    raise LLMError(f"{self._name} does not know the model “{current}”. Set MEDBRIDGE_MODEL in .env to a model "
                                   f"listed at {self._base.rsplit('/openai', 1)[0]} ({exc})") from exc
                log.warning("%s model %s is not available; switching to %s. Set MEDBRIDGE_MODEL=%s to make it permanent.",
                            self._name, current, alt, alt)
                self._resolved[model] = current = alt
                swapped = True
                continue
            except _BadRequest as exc:
                if self._mode == "json_schema" and _FORMAT_PROBLEM.search(exc.text):
                    log.warning("%s model %s does not support strict schemas; using plain JSON mode.", self._name, current)
                    self._mode = "json_object"
                    continue
                raise LLMError(f"{self._name} rejected the request: {exc.text}") from exc

            choice = (data.get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
            parsed, problem = self._validate(content, output_format)
            if parsed is None and problem and content.strip() and not repaired:
                repaired = True  # one chance to fix its own answer
                extra = [{"role": "assistant", "content": content},
                         {"role": "user", "content": f"That JSON was not accepted ({problem}). Reply with the corrected JSON only."}]
                continue
            finish = choice.get("finish_reason")
            return SimpleNamespace(parsed_output=parsed, stop_reason="; ".join(x for x in (finish, problem) if x) or None)
        raise LLMError(f"{self._name} did not give a usable answer after several tries.")


class AnthropicClient:
    default_model = ANTHROPIC_DEFAULT_MODEL

    def __init__(self):
        import anthropic

        self.messages = anthropic.Anthropic().messages


def selected_provider() -> str:
    """Which provider the environment points to (empty string if none)."""
    provider = (os.environ.get("MEDBRIDGE_LLM") or "").lower().replace("-", "_")
    if provider:
        return provider
    if os.environ.get("GROQ_API_KEY"):
        return "groq"
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return "gemini"
    return "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else ""


def make_client(provider: str | None = None) -> Any:
    groq_key = os.environ.get("GROQ_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    provider = (provider or os.environ.get("MEDBRIDGE_LLM") or "").lower().replace("-", "_")
    if not provider:
        provider = ("groq" if groq_key else "gemini" if gemini_key else
                    "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "")
    if provider == "groq":
        if not groq_key:
            raise LLMError(NO_KEY_MESSAGE)
        return OpenAICompatClient(groq_key, GROQ_BASE_URL, GROQ_DEFAULT_MODEL, name="Groq")
    if provider in ("openai_compat", "openai_compatible", "local", "ollama"):
        base = os.environ.get("LLM_BASE_URL")
        if not base:
            raise LLMError("MEDBRIDGE_LLM=openai_compat needs LLM_BASE_URL (for example http://localhost:11434/v1 for Ollama).")
        return OpenAICompatClient(os.environ.get("LLM_API_KEY") or "none", base, os.environ.get("MEDBRIDGE_MODEL") or "llama3.1",
                                  name="The AI service", preferred=())
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

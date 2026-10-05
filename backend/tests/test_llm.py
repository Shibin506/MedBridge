import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from google.genai import errors

from app.extractor import Extractor
from app.llm import AnthropicClient, GeminiClient, LLMError, LLMUnavailable, make_client, model_for
from app.main import app, get_extractor
from app.schemas import ExtractionDraft
from conftest import SAMPLES, draft_for_heart_failure


class FakeGenAI:
    """Stands in for google.genai.Client: records the call, returns or raises what we tell it."""

    def __init__(self, *, parsed=None, text=None, raises=None, finish="STOP"):
        self.calls = []
        self._resp = SimpleNamespace(parsed=parsed, text=text, candidates=[SimpleNamespace(finish_reason=finish)])
        self._raises = raises
        self.models = SimpleNamespace(generate_content=self._generate)

    def _generate(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise self._raises
        return self._resp


def ask(fake, **kw):
    return GeminiClient(client=fake).messages.parse(
        model="gemini-test", max_tokens=1234, system="SYS", messages=[{"role": "user", "content": "DOC"}],
        output_format=ExtractionDraft, **kw)


def test_request_asks_gemini_for_json_in_our_exact_schema():
    fake = FakeGenAI(parsed=draft_for_heart_failure())
    ask(fake)
    call = fake.calls[0]
    assert call["model"] == "gemini-test" and call["contents"] == "DOC"
    cfg = call["config"]
    assert cfg.system_instruction == "SYS"
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema is ExtractionDraft
    assert cfg.max_output_tokens == 1234


def test_parsed_object_is_passed_through():
    draft = draft_for_heart_failure()
    out = ask(FakeGenAI(parsed=draft))
    assert out.parsed_output is draft and out.stop_reason == "STOP"


def test_falls_back_to_parsing_the_json_text():
    text = draft_for_heart_failure().model_dump_json()
    out = ask(FakeGenAI(parsed=None, text=text))
    assert isinstance(out.parsed_output, ExtractionDraft)
    assert out.parsed_output.medications[0].name == "Furosemide"


@pytest.mark.parametrize("text", [None, "", "not json", '{"medications": "oops"}', '{"medications": ['])
def test_unusable_answer_gives_none_not_a_crash(text):
    out = ask(FakeGenAI(parsed=None, text=text, finish="MAX_TOKENS"))
    assert out.parsed_output is None and out.stop_reason.startswith("MAX_TOKENS")


def test_stop_reason_says_what_was_wrong_without_leaking_content():
    bad = '{"diagnosis_summary": "SECRET PATIENT DETAIL", "medications": "not a list"}'
    out = ask(FakeGenAI(parsed=None, text=bad))
    assert out.parsed_output is None
    assert "did not match the expected shape" in out.stop_reason and "medications" in out.stop_reason
    assert "SECRET PATIENT DETAIL" not in out.stop_reason
    assert "empty answer" in ask(FakeGenAI(parsed=None, text="")).stop_reason


def test_function_calling_is_switched_off():
    fake = FakeGenAI(parsed=draft_for_heart_failure())
    ask(fake)
    assert fake.calls[0]["config"].automatic_function_calling.disable is True


def test_ai_errors_are_written_to_the_server_log(caplog):
    import logging
    class Bad:
        messages = SimpleNamespace(parse=lambda **k: (_ for _ in ()).throw(LLMError("Gemini does not know that model")))
    app.dependency_overrides[get_extractor] = lambda: Extractor(client=Bad())
    try:
        with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
            r = TestClient(app).post("/extract", files={"file": ("a.txt", (SAMPLES / "01_heart_failure.txt").read_bytes(), "text/plain")})
        assert r.status_code == 502
        assert "AI error on /extract: Gemini does not know that model" in caplog.text
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize("code", [429, 500, 503])
def test_busy_errors_are_retryable(code):
    exc = errors.APIError(code, {"error": {"message": "slow down"}})
    with pytest.raises(LLMUnavailable):
        ask(FakeGenAI(raises=exc))


def test_other_api_errors_are_not_retryable():
    with pytest.raises(LLMError) as e:
        ask(FakeGenAI(raises=errors.APIError(400, {"error": {"message": "bad request"}})))
    assert not isinstance(e.value, LLMUnavailable)


@pytest.mark.parametrize("code,message,expected", [
    (400, "API key not valid. Please pass a valid API key.", "rejected the API key"),
    (403, "forbidden", "rejected the API key"),
    (404, "models/foo is not found", "does not know that model"),
])
def test_common_setup_mistakes_get_plain_english_messages(code, message, expected):
    with pytest.raises(LLMError) as e:
        ask(FakeGenAI(raises=errors.APIError(code, {"error": {"message": message}})))
    assert expected in str(e.value)


def test_network_failure_counts_as_unavailable():
    with pytest.raises(LLMUnavailable):
        ask(FakeGenAI(raises=ConnectionError("no wifi")))


def test_extractor_works_end_to_end_through_the_gemini_adapter():
    text = (SAMPLES / "01_heart_failure.txt").read_text(encoding="utf-8")
    fake = FakeGenAI(parsed=draft_for_heart_failure())
    result = Extractor(client=GeminiClient(client=fake)).extract(text)
    assert fake.calls[0]["model"] == "gemini-2.5-flash"  # provider default
    assert result.items_needing_confirmation == 1  # the invented warfarin is still caught by our checker


# ---------- choosing a provider ----------
@pytest.fixture
def clean_env(monkeypatch):
    for k in ("MEDBRIDGE_LLM", "MEDBRIDGE_MODEL", "GEMINI_API_KEY", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_gemini_key_selects_gemini(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "x")
    assert isinstance(make_client(), GeminiClient)
    clean_env.delenv("GEMINI_API_KEY"); clean_env.setenv("GOOGLE_API_KEY", "x")
    assert isinstance(make_client(), GeminiClient)


def test_anthropic_key_selects_claude_when_no_gemini_key(clean_env):
    clean_env.setenv("ANTHROPIC_API_KEY", "x")
    assert isinstance(make_client(), AnthropicClient)


def test_gemini_wins_when_both_keys_exist_unless_overridden(clean_env):
    clean_env.setenv("GEMINI_API_KEY", "x"); clean_env.setenv("ANTHROPIC_API_KEY", "y")
    assert isinstance(make_client(), GeminiClient)
    clean_env.setenv("MEDBRIDGE_LLM", "anthropic")
    assert isinstance(make_client(), AnthropicClient)


def test_no_key_gives_a_helpful_message(clean_env):
    with pytest.raises(LLMError) as e:
        make_client()
    assert "aistudio.google.com/apikey" in str(e.value) and ".env" in str(e.value)
    clean_env.setenv("MEDBRIDGE_LLM", "gemini")
    with pytest.raises(LLMError):
        make_client()


def test_model_choice_order(clean_env):
    gem = GeminiClient(api_key="x")
    assert model_for(gem, None) == "gemini-2.5-flash"
    clean_env.setenv("MEDBRIDGE_MODEL", "gemini-custom")
    assert model_for(gem, None) == "gemini-custom"
    assert model_for(gem, "explicit") == "explicit"


# ---------- API turns AI trouble into friendly errors ----------
def test_api_maps_ai_errors_to_clear_http_statuses(clean_env):
    text = (SAMPLES / "01_heart_failure.txt").read_bytes()
    files = {"file": ("a.txt", text, "text/plain")}

    class Busy:
        messages = SimpleNamespace(parse=lambda **k: (_ for _ in ()).throw(LLMUnavailable("429")))

    app.dependency_overrides[get_extractor] = lambda: Extractor(client=Busy())
    try:
        r = TestClient(app).post("/extract", files=files)
        assert r.status_code == 503 and "try again" in r.json()["detail"]
    finally:
        app.dependency_overrides.clear()

    r = TestClient(app).post("/extract", files=files)  # no key set, not demo mode
    assert r.status_code == 502 and "aistudio.google.com/apikey" in r.json()["detail"]

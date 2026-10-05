import json

import httpx
import pytest

from app.llm import (
    GROQ_DEFAULT_MODEL,
    GeminiClient,
    LLMError,
    LLMUnavailable,
    OpenAICompatClient,
    make_client,
    pick_chat_model,
    strict_schema,
)
from app.schemas import ExtractionDraft
from conftest import draft_for_heart_failure


class FakeGroq:
    """A pretend Groq server. `script` is a list of replies, one per call; each is (status, json_body)."""

    def __init__(self, *script):
        self.script, self.requests = list(script), []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        self.requests.append((request.method, request.url.path, body, request.headers.get("authorization")))
        status, payload = self.script.pop(0) if self.script else (500, {"error": {"message": "script exhausted"}})
        return httpx.Response(status, json=payload)

    def client(self) -> OpenAICompatClient:
        http = httpx.Client(transport=httpx.MockTransport(self.handler))
        return OpenAICompatClient("gsk_" + "TESTONLY" * 4, "https://api.groq.test/openai/v1", GROQ_DEFAULT_MODEL, client=http)


def answer(text: str, finish: str = "stop"):
    return 200, {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": finish}]}


GOOD = draft_for_heart_failure().model_dump_json()


def ask(client, model=GROQ_DEFAULT_MODEL):
    return client.messages.parse(model=model, max_tokens=16000, system="SYS",
                                 messages=[{"role": "user", "content": "DOC"}], output_format=ExtractionDraft)


# ---------- the request we send ----------
def test_request_uses_strict_json_schema_and_the_key():
    fake = FakeGroq(answer(GOOD))
    out = ask(fake.client())
    method, path, body, auth = fake.requests[0]
    assert (method, path) == ("POST", "/openai/v1/chat/completions")
    assert auth == "Bearer gsk_" + "TESTONLY" * 4
    assert body["model"] == GROQ_DEFAULT_MODEL and body["temperature"] == 0
    assert body["max_tokens"] == 6000  # capped for free-tier per-minute limits
    assert body["messages"][0] == {"role": "system", "content": "SYS"}
    assert body["messages"][1] == {"role": "user", "content": "DOC"}
    fmt = body["response_format"]
    assert fmt["type"] == "json_schema" and fmt["json_schema"]["strict"] is True
    assert fmt["json_schema"]["name"] == "ExtractionDraft"
    assert out.parsed_output.medications[0].name == "Furosemide" and out.stop_reason == "stop"


def test_strict_schema_closes_every_object_and_requires_every_field():
    schema = strict_schema(ExtractionDraft.model_json_schema())

    def objects(node):
        if isinstance(node, dict):
            if "properties" in node:
                yield node
            for v in node.values():
                yield from objects(v)
        elif isinstance(node, list):
            for v in node:
                yield from objects(v)

    found = list(objects(schema))
    assert len(found) >= 5  # the draft plus its nested models
    for obj in found:
        assert obj["additionalProperties"] is False
        assert obj["required"] == list(obj["properties"])
    # field NAMES are not mistaken for schema keywords
    med = schema["$defs"]["MedicationDraft"]
    assert "source_quote" in med["properties"] and "route" in med["properties"]


# ---------- coping with models that cannot do strict schemas ----------
def test_falls_back_to_plain_json_mode_and_remembers():
    fake = FakeGroq(
        (400, {"error": {"message": "response_format json_schema is not supported with this model"}}),
        answer(GOOD),
        answer(GOOD),
    )
    client = fake.client()
    assert ask(client).parsed_output is not None
    second = fake.requests[1][2]
    assert second["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in second["messages"][0]["content"] and "MedicationDraft" in second["messages"][0]["content"]
    ask(client)  # remembered: goes straight to plain JSON mode
    assert fake.requests[2][2]["response_format"] == {"type": "json_object"} and len(fake.requests) == 3


def test_unrelated_bad_request_is_reported_not_retried():
    fake = FakeGroq((400, {"error": {"message": "max_tokens must be less than 1000"}}))
    with pytest.raises(LLMError) as e:
        ask(fake.client())
    assert "rejected the request" in str(e.value) and len(fake.requests) == 1


# ---------- messy answers ----------
@pytest.mark.parametrize("wrap", ["```json\n{}\n```", "Here you go:\n{}\nHope it helps!", "{}"])
def test_json_wrapped_in_chatter_or_code_fences_is_accepted(wrap):
    assert ask(FakeGroq(answer(wrap.replace("{}", GOOD))).client()).parsed_output is not None


def test_one_repair_attempt_when_json_does_not_match():
    bad = '{"diagnosis_summary": "x", "medications": "not a list"}'
    fake = FakeGroq(answer(bad), answer(GOOD))
    out = ask(fake.client())
    assert out.parsed_output is not None and len(fake.requests) == 2
    repair_msgs = fake.requests[1][2]["messages"]
    assert repair_msgs[-2] == {"role": "assistant", "content": bad}
    assert "not accepted" in repair_msgs[-1]["content"] and "medications" in repair_msgs[-1]["content"]


def test_gives_up_after_one_repair_without_leaking_content():
    bad = '{"diagnosis_summary": "SECRET PATIENT DETAIL", "medications": "nope"}'
    out = ask(FakeGroq(answer(bad), answer(bad)).client())
    assert out.parsed_output is None
    assert "did not match the expected shape" in out.stop_reason and "SECRET PATIENT DETAIL" not in out.stop_reason


def test_empty_answer_gives_none_with_reason():
    out = ask(FakeGroq(answer("", finish="length")).client())
    assert out.parsed_output is None and out.stop_reason == "length; empty answer"


# ---------- errors ----------
@pytest.mark.parametrize("status", [401, 403])
def test_bad_key_message_points_to_the_fix(status):
    with pytest.raises(LLMError) as e:
        ask(FakeGroq((status, {"error": {"message": "Invalid API Key"}})).client())
    assert "rejected the API key" in str(e.value) and "set-key.sh" in str(e.value) and "gsk_" in str(e.value)
    assert not isinstance(e.value, LLMUnavailable)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_busy_is_retryable(status):
    with pytest.raises(LLMUnavailable):
        ask(FakeGroq((status, {"error": {"message": "slow down"}})).client())


def test_too_large_for_free_limit_is_a_plain_error():
    with pytest.raises(LLMError) as e:
        ask(FakeGroq((413, {"error": {"message": "Request too large for model: tokens per minute (TPM) limit 8000"}})).client())
    assert "too big" in str(e.value) and not isinstance(e.value, LLMUnavailable)


def test_network_failure_is_retryable():
    def boom(request):
        raise httpx.ConnectError("no wifi")

    client = OpenAICompatClient("k", "https://x.test/v1", "m", client=httpx.Client(transport=httpx.MockTransport(boom)))
    with pytest.raises(LLMUnavailable):
        ask(client)


def test_the_key_never_appears_in_error_text():
    key = "gsk_" + "TESTONLY" * 4
    fake = FakeGroq((418, {"error": {"message": f"weird failure for {key}"}}))
    with pytest.raises(LLMError) as e:
        ask(fake.client())
    assert key not in str(e.value)


# ---------- model names that stop existing ----------
def test_unknown_model_is_replaced_by_the_best_available_one():
    fake = FakeGroq(
        (404, {"error": {"message": "The model `old-model` does not exist"}}),
        (200, {"data": [{"id": "whisper-large-v3"}, {"id": "llama-3.3-70b-versatile"}, {"id": "openai/gpt-oss-20b"}]}),
        answer(GOOD),
        answer(GOOD),
    )
    client = fake.client()
    assert ask(client, model="old-model").parsed_output is not None
    assert [r[2]["model"] for r in fake.requests if r[0] == "POST"] == ["old-model", "openai/gpt-oss-20b"]
    assert fake.requests[1][:2] == ("GET", "/openai/v1/models")
    ask(client, model="old-model")  # remembered
    assert fake.requests[-1][2]["model"] == "openai/gpt-oss-20b"


def test_unknown_model_and_no_alternative_gives_plain_message():
    fake = FakeGroq((404, {"error": {"message": "no such model"}}), (200, {"data": []}))
    with pytest.raises(LLMError) as e:
        ask(fake.client(), model="old-model")
    assert "does not know the model" in str(e.value) and "MEDBRIDGE_MODEL" in str(e.value)


def test_pick_chat_model_prefers_the_list_and_skips_non_chat_models():
    ids = ["whisper-large-v3", "llama-guard-4", "some-new-model", "llama-3.3-70b-versatile", "playai-tts"]
    assert pick_chat_model(ids, ("openai/gpt-oss-120b", "llama-3.3-70b-versatile")) == "llama-3.3-70b-versatile"
    assert pick_chat_model(ids, ()) == "some-new-model"
    assert pick_chat_model(["whisper-large-v3"], ()) is None
    assert pick_chat_model(["a", "b"], (), exclude="a") == "b"


# ---------- choosing Groq ----------
@pytest.fixture
def clean_env(monkeypatch):
    for k in ("MEDBRIDGE_LLM", "MEDBRIDGE_MODEL", "GROQ_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY",
              "ANTHROPIC_API_KEY", "LLM_BASE_URL", "LLM_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def test_groq_key_selects_groq_even_if_a_gemini_key_is_also_present(clean_env):
    clean_env.setenv("GROQ_API_KEY", "gsk_x"); clean_env.setenv("GEMINI_API_KEY", "old-bad-key")
    client = make_client()
    assert isinstance(client, OpenAICompatClient) and client.default_model == GROQ_DEFAULT_MODEL


def test_can_still_force_gemini(clean_env):
    clean_env.setenv("GROQ_API_KEY", "gsk_x"); clean_env.setenv("GEMINI_API_KEY", "g"); clean_env.setenv("MEDBRIDGE_LLM", "gemini")
    assert isinstance(make_client(), GeminiClient)


def test_groq_selected_but_key_missing_explains(clean_env):
    clean_env.setenv("MEDBRIDGE_LLM", "groq")
    with pytest.raises(LLMError) as e:
        make_client()
    assert "console.groq.com/keys" in str(e.value) and "set-key.sh" in str(e.value)


def test_any_openai_compatible_server_such_as_ollama(clean_env):
    clean_env.setenv("MEDBRIDGE_LLM", "openai_compat"); clean_env.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    client = make_client()
    assert isinstance(client, OpenAICompatClient) and client._base == "http://localhost:11434/v1" and client._key == "none"
    clean_env.delenv("LLM_BASE_URL")
    with pytest.raises(LLMError):
        make_client()

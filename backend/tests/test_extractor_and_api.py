from fastapi.testclient import TestClient

from app.extractor import SYSTEM_PROMPT, Extractor
from app.main import app, get_extractor
from app.schemas import ExtractionDraft
from conftest import FakeClient, SAMPLES, draft_for_heart_failure


def test_extractor_sends_document_and_schema(heart_text):
    client = FakeClient(draft_for_heart_failure())
    result = Extractor(client=client, model="test-model").extract(heart_text)

    call = client.calls[0]
    assert call["model"] == "test-model"
    assert call["output_format"] is ExtractionDraft
    assert call["system"] == SYSTEM_PROMPT
    assert "Furosemide" in call["messages"][0]["content"]
    assert result.items_needing_confirmation == 1  # the hallucinated warfarin


def test_api_extract_endpoint_end_to_end():
    fake = Extractor(client=FakeClient(draft_for_heart_failure()))
    app.dependency_overrides[get_extractor] = lambda: fake
    try:
        http = TestClient(app)
        assert http.get("/health").json() == {"status": "ok"}
        pdf = (SAMPLES / "01_heart_failure.pdf").read_bytes()
        r = http.post("/extract", files={"file": ("discharge.pdf", pdf, "application/pdf")})
        assert r.status_code == 200
        body = r.json()
        assert body["medications"][0]["name"] == "Furosemide"
        assert body["medications"][1]["grounded"] is False
    finally:
        app.dependency_overrides.clear()


def test_api_rejects_unsupported_file():
    http = TestClient(app)
    r = http.post("/extract", files={"file": ("x.png", b"123", "image/png")})
    assert r.status_code == 422

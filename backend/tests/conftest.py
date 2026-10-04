import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.schemas import ExtractionDraft  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


@pytest.fixture
def heart_text() -> str:
    return (SAMPLES / "01_heart_failure.txt").read_text(encoding="utf-8")


def draft_for_heart_failure() -> ExtractionDraft:
    """A hand-written 'LLM answer': two correct items and one hallucinated one."""
    return ExtractionDraft.model_validate(
        {
            "diagnosis_summary": "Admitted for worsening congestive heart failure.",
            "medications": [
                {
                    "name": "Furosemide", "dose": "40 mg", "route": "by mouth",
                    "frequency": "every morning", "duration": None,
                    "purpose": "water pill to remove extra fluid", "instructions": "take early in the day",
                    "status": "new",
                    "source_quote": "Furosemide (Lasix) 40 mg tablet - take 1 tablet by mouth every morning",
                },
                {
                    # Hallucinated: the document never mentions warfarin.
                    "name": "Warfarin", "dose": "5 mg", "route": "by mouth",
                    "frequency": "once daily", "duration": None, "purpose": None, "instructions": None,
                    "status": "new",
                    "source_quote": "Warfarin 5 mg once daily at night",
                },
            ],
            "follow_ups": [
                {
                    "what": "Cardiology clinic visit", "with_whom": "Dr. Okafor", "when": "within 7 days",
                    "source_quote": "Cardiology clinic (Dr. Okafor): within 7 days.",
                }
            ],
            "warning_signs": [],
            "restrictions": [],
            "unclear_items": [],
        }
    )


class FakeClient:
    """Stands in for anthropic.Anthropic() so tests never touch the network."""

    def __init__(self, draft: ExtractionDraft):
        self.calls: list[dict] = []
        self.messages = SimpleNamespace(parse=self._parse)
        self._draft = draft

    def _parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self._draft, stop_reason="end_turn")

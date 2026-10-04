from app.verify import normalize, verify
from conftest import draft_for_heart_failure


def test_normalize_collapses_whitespace_quotes_and_hyphenation():
    assert normalize("Do  not\n  take “this”") == 'do not take "this"'
    assert normalize("medi-\ncation") == "medication"


def test_real_quote_is_grounded(heart_text):
    result = verify(draft_for_heart_failure(), heart_text)
    furosemide = result.medications[0]
    assert furosemide.grounded is True
    assert furosemide.issues == []


def test_hallucinated_item_is_flagged(heart_text):
    result = verify(draft_for_heart_failure(), heart_text)
    warfarin = result.medications[1]
    assert warfarin.grounded is False
    assert warfarin.needs_confirmation is True
    assert "not found in the document" in warfarin.issues[0]


def test_missing_dose_or_frequency_needs_confirmation(heart_text):
    draft = draft_for_heart_failure()
    draft.medications[0].dose = None
    result = verify(draft, heart_text)
    assert result.medications[0].needs_confirmation is True


def test_drug_name_must_appear_in_its_quote(heart_text):
    draft = draft_for_heart_failure()
    draft.medications[0].name = "Digoxin"  # quote is real but about furosemide
    result = verify(draft, heart_text)
    assert result.medications[0].grounded is False


def test_quote_wrapped_across_lines_still_matches(heart_text):
    draft = draft_for_heart_failure()
    # In the document this sentence wraps across a line break.
    draft.medications[0].source_quote = "water pill to remove extra fluid. You may urinate more often"
    draft.medications[0].name = "water pill"
    result = verify(draft, heart_text)
    assert result.medications[0].grounded is True


def test_counts(heart_text):
    result = verify(draft_for_heart_failure(), heart_text)
    assert result.total_items == 3
    # warfarin flagged; furosemide ok; follow-up ok
    assert result.items_needing_confirmation == 1

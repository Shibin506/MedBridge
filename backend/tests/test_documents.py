from pathlib import Path

import pytest

from app.documents import UnreadableDocument, load_document

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def test_pdf_text_is_extracted():
    text = load_document("x.pdf", (SAMPLES / "01_heart_failure.pdf").read_bytes())
    assert "Furosemide" in text and "CALL 911" in text


def test_txt_loads():
    assert "Atorvastatin" in load_document("a.txt", (SAMPLES / "01_heart_failure.txt").read_bytes())


def test_rejects_unknown_type():
    with pytest.raises(UnreadableDocument):
        load_document("photo.png", b"\x89PNG")


def test_rejects_garbage_pdf():
    with pytest.raises(UnreadableDocument):
        load_document("bad.pdf", b"not a pdf")


def test_rejects_empty_text():
    with pytest.raises(UnreadableDocument):
        load_document("a.txt", b"hi")

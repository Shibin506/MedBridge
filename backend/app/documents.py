"""Turn an uploaded file into plain text we can both send to the LLM and search."""

import io

from pypdf import PdfReader

MIN_TEXT_CHARS = 200  # fewer than this from a PDF almost always means a scan


class UnreadableDocument(ValueError):
    """The file could not be turned into usable text."""


def pdf_to_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # pypdf raises many different errors on bad files
        raise UnreadableDocument(f"Could not read the PDF: {exc}") from exc
    if len(text.strip()) < MIN_TEXT_CHARS:
        raise UnreadableDocument(
            "This PDF has almost no selectable text; it is probably a scan or photo. "
            "Scan/photo support is planned for a later phase."
        )
    return text


def load_document(filename: str, data: bytes) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return pdf_to_text(data)
    if name.endswith(".txt"):
        text = data.decode("utf-8", errors="replace")
        if len(text.strip()) < MIN_TEXT_CHARS:
            raise UnreadableDocument("The text file is too short to be a discharge summary.")
        return text
    raise UnreadableDocument("Unsupported file type. Please upload a PDF or .txt file.")

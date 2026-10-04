"""Render samples/*.txt into text PDFs (so we can test the PDF path without real documents).

Run:  python scripts/make_sample_pdfs.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


def txt_to_pdf(txt_path: Path, pdf_path: Path) -> None:
    c = canvas.Canvas(str(pdf_path), pagesize=letter)
    width, height = letter
    y = height - 54
    c.setFont("Helvetica", 10)
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        if y < 54:
            c.showPage()
            c.setFont("Helvetica", 10)
            y = height - 54
        c.drawString(54, y, line[:110])
        y -= 13
    c.save()


if __name__ == "__main__":
    for txt in sorted(SAMPLES.glob("*.txt")):
        pdf = txt.with_suffix(".pdf")
        txt_to_pdf(txt, pdf)
        print("wrote", pdf.name)

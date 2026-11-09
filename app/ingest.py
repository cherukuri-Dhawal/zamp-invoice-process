"""Stage 1: Ingest — read a PDF, return raw text and whether it has a text layer.

If a PDF has no extractable text layer (a scanned/flattened invoice, EC1), we
rasterize it with PyMuPDF and fall back to Tesseract OCR. OCR output is
inherently noisier than a text layer, so we flag a lower confidence rather
than silently trusting it -- extract.py uses that confidence to decide
whether to also lean on the Gemini assist for messy text.
"""
import os
import shutil
from pathlib import Path
from typing import TypedDict

import pdfplumber
import pytesseract

# pytesseract needs to find the tesseract.exe binary. If it's not already on
# PATH, fall back to the default Windows install location.
if shutil.which("tesseract") is None:
    _default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_default_win_path):
        pytesseract.pytesseract.tesseract_cmd = _default_win_path


class IngestResult(TypedDict):
    text: str
    page_count: int
    has_text_layer: bool
    ocr_used: bool
    confidence: float


def _ocr_pdf(filepath: Path) -> str:
    try:
        import pymupdf as fitz
    except ImportError:
        return ""

    from PIL import Image
    import io

    texts = []
    doc = fitz.open(str(filepath))
    try:
        for page in doc:
            # 200 dpi: ~11 MB/page uncompressed vs ~26 MB at 300 dpi.
            # Still well above Tesseract's minimum legibility threshold (~150 dpi).
            # Explicit del releases the pixmap buffer before the next page loads,
            # keeping peak RSS under ~25 MB per page on Render's 512 MB free tier.
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            texts.append(pytesseract.image_to_string(img))
            del pix
    finally:
        doc.close()
    return "\n".join(texts).strip()


def ingest_pdf(filepath: str | Path) -> IngestResult:
    filepath = Path(filepath)
    pages_text: list[str] = []

    with pdfplumber.open(filepath) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            pages_text.append(page_text)

    full_text = "\n".join(pages_text).strip()
    has_text_layer = len(full_text) >= 20

    if has_text_layer:
        return {
            "text": full_text,
            "page_count": page_count,
            "has_text_layer": True,
            "ocr_used": False,
            "confidence": 1.0,
        }

    ocr_text = _ocr_pdf(filepath)
    return {
        "text": ocr_text,
        "page_count": page_count,
        "has_text_layer": False,
        "ocr_used": True,
        # OCR on a flattened/noisy scan is never fully trusted -- downstream
        # stages must treat this as a low-confidence extraction.
        "confidence": 0.6 if ocr_text else 0.0,
    }

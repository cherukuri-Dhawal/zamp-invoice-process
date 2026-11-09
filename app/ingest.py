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


def _try_paddleocr(img) -> str | None:
    """PaddleOCR optional fast path — higher accuracy on amounts and skewed text.
    Returns None if paddleocr is not installed or fails (Tesseract fallback takes over).
    Not used on Render free tier by default: set ENABLE_PADDLEOCR=1 env var to activate.
    Memory note: PaddleOCR model load is ~200-300 MB; only safe if container has > 400 MB free."""
    import os
    if not os.environ.get("ENABLE_PADDLEOCR"):
        return None
    try:
        from paddleocr import PaddleOCR
        import numpy as np
        ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
        result = ocr.ocr(np.array(img), cls=True)
        lines = [line[1][0] for block in (result or []) for line in (block or []) if line and line[1]]
        return "\n".join(lines).strip() or None
    except Exception:
        return None


def _ocr_pdf(filepath: Path) -> tuple[str, str]:
    """Returns (text, method) where method is 'paddleocr' or 'tesseract'."""
    try:
        import pymupdf as fitz
    except ImportError:
        return "", "tesseract"

    from PIL import Image
    import io

    texts = []
    method = "tesseract"
    # Tesseract config: LSTM engine (oem 3) + assume uniform text block (psm 6).
    # This is meaningfully more accurate than default on structured invoice layouts.
    tess_config = "--oem 3 --psm 6"

    doc = fitz.open(str(filepath))
    try:
        for page in doc:
            # 200 dpi: ~11 MB/page uncompressed vs ~26 MB at 300 dpi.
            # Still well above Tesseract's minimum legibility threshold (~150 dpi).
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            del pix

            paddle_text = _try_paddleocr(img)
            if paddle_text:
                texts.append(paddle_text)
                method = "paddleocr"
            else:
                texts.append(pytesseract.image_to_string(img, config=tess_config))
    finally:
        doc.close()
    return "\n".join(texts).strip(), method


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
            "ocr_method": "none",
            "confidence": 1.0,
        }

    ocr_text, ocr_method = _ocr_pdf(filepath)
    # PaddleOCR is significantly more accurate on structured invoices (0.9),
    # Tesseract is reliable but noisier (0.6). Both are below the 0.8 auto-approve
    # threshold so a human review is always required for scanned invoices.
    ocr_confidence = 0.9 if ocr_method == "paddleocr" else (0.6 if ocr_text else 0.0)
    return {
        "text": ocr_text,
        "page_count": page_count,
        "has_text_layer": False,
        "ocr_used": True,
        "ocr_method": ocr_method,
        "confidence": ocr_confidence,
    }

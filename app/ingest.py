"""Stage 1: Ingest — read a PDF, return raw text and whether it has a text layer.

For text-layer PDFs: pdfplumber extracts text directly (fast, confidence 1.0).
For scanned/image PDFs: rasterize with PyMuPDF, then OCR via:
  1. Gemini Vision (primary, if GEMINI_API_KEY set) — confidence 0.85
  2. Tesseract fallback (if Gemini unavailable)       — confidence 0.6
Both are below the 0.8 auto-approve threshold, so scanned invoices always
get a human-review hold regardless of which OCR method ran.
"""
import io
import os
import shutil
from pathlib import Path
from typing import TypedDict

import pdfplumber
import pytesseract

# pytesseract needs to find the tesseract.exe binary on Windows.
if shutil.which("tesseract") is None:
    _default_win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(_default_win_path):
        pytesseract.pytesseract.tesseract_cmd = _default_win_path


class IngestResult(TypedDict):
    text: str
    page_count: int
    has_text_layer: bool
    ocr_used: bool
    ocr_method: str
    confidence: float


def _gemini_vision_ocr(img_bytes: bytes, gemini_key: str) -> str | None:
    """Send a rasterized page image to Gemini Vision and return extracted text.
    Returns None on any failure so Tesseract fallback takes over."""
    try:
        import google.generativeai as genai
        import base64

        genai.configure(api_key=gemini_key, transport="rest")
        model = genai.GenerativeModel("gemini-2.0-flash")

        img_b64 = base64.b64encode(img_bytes).decode()
        response = model.generate_content(
            [
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": img_b64,
                    }
                },
                (
                    "Extract all text from this invoice image exactly as it appears. "
                    "Preserve line breaks and spacing. Output only the raw text, "
                    "no commentary or markdown."
                ),
            ],
            request_options={"timeout": 20},
        )
        text = (response.text or "").strip()
        return text if len(text) >= 10 else None
    except Exception:
        return None


def _try_paddleocr(img) -> str | None:
    """PaddleOCR optional path — set ENABLE_PADDLEOCR=1 to activate.
    Not used on Render free tier by default (model load ~200-300 MB)."""
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


def _ocr_pdf(filepath: Path, gemini_key: str | None) -> tuple[str, str]:
    """Rasterize PDF pages and OCR them. Returns (text, method)."""
    try:
        import pymupdf as fitz
    except ImportError:
        return "", "tesseract"

    from PIL import Image

    texts: list[str] = []
    method = "tesseract"
    tess_config = "--oem 3 --psm 6"

    doc = fitz.open(str(filepath))
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img_bytes = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_bytes))
            del pix

            # Priority: Gemini Vision → PaddleOCR (opt-in) → Tesseract
            if gemini_key:
                vision_text = _gemini_vision_ocr(img_bytes, gemini_key)
                if vision_text:
                    texts.append(vision_text)
                    method = "gemini_vision"
                    continue

            paddle_text = _try_paddleocr(img)
            if paddle_text:
                texts.append(paddle_text)
                method = "paddleocr"
                continue

            texts.append(pytesseract.image_to_string(img, config=tess_config))
    finally:
        doc.close()

    return "\n".join(texts).strip(), method


def ingest_pdf(filepath: str | Path, gemini_key: str | None = None) -> IngestResult:
    filepath = Path(filepath)
    pages_text: list[str] = []

    with pdfplumber.open(filepath) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages:
            pages_text.append(page.extract_text() or "")

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

    ocr_text, ocr_method = _ocr_pdf(filepath, gemini_key)
    confidence_map = {"gemini_vision": 0.85, "paddleocr": 0.9, "tesseract": 0.6}
    ocr_confidence = confidence_map.get(ocr_method, 0.6) if ocr_text else 0.0

    return {
        "text": ocr_text,
        "page_count": page_count,
        "has_text_layer": False,
        "ocr_used": True,
        "ocr_method": ocr_method,
        "confidence": ocr_confidence,
    }

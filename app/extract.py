"""Stage 2: Extract — pull structured fields out of raw invoice text.

Primary path is deterministic regex parsing (works for our clean, reportlab-
generated invoices and most real text-layer PDFs with a reasonably standard
layout). Gemini is used ONLY as a fallback assist when regex extraction comes
back incomplete (e.g. messy/garbled OCR text) -- it parses free text into the
same structured JSON shape. It never decides anything; decide.py (deterministic
code) makes the approve/hold/reject call downstream.
"""
import json
import re
from pathlib import Path
from typing import Optional, TypedDict

REQUIRED_FIELDS = ("vendor", "invoice_num", "date", "total")


class LineItem(TypedDict):
    description: str
    qty: float
    unit_price: float
    amount: float


class ExtractedFields(TypedDict):
    vendor: Optional[str]
    invoice_num: Optional[str]
    date: Optional[str]
    line_items: list[LineItem]
    subtotal: Optional[float]
    tax: Optional[float]
    total: Optional[float]
    po_reference: Optional[str]
    extraction_confidence: float
    extraction_method: str


_MONEY = r"[\d,]+(?:\.\d+)?"


def _to_number(s: str) -> Optional[float]:
    try:
        return float(s.replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def _regex_extract(raw_text: str) -> ExtractedFields:
    lines = [l for l in raw_text.splitlines() if l.strip()]
    vendor = lines[0].strip() if lines else None

    invoice_num = None
    m = re.search(r"Invoice\s*#:\s*(.+)", raw_text, re.IGNORECASE)
    if m:
        invoice_num = m.group(1).strip()

    date = None
    m = re.search(r"Date:\s*([\d/-]+)", raw_text, re.IGNORECASE)
    if m:
        date = m.group(1).strip()

    po_reference = None
    m = re.search(r"PO\s*Reference:\s*(\S+)", raw_text, re.IGNORECASE)
    if m:
        po_reference = m.group(1).strip()

    subtotal = None
    m = re.search(rf"Subtotal:\s*({_MONEY})", raw_text, re.IGNORECASE)
    if m:
        subtotal = _to_number(m.group(1))

    tax = None
    m = re.search(rf"\bTax:\s*({_MONEY})", raw_text, re.IGNORECASE)
    if m:
        tax = _to_number(m.group(1))

    total = None
    m = re.search(rf"(?<![a-zA-Z])Total(?:\s*\(tax incl\.\))?:\s*({_MONEY})", raw_text, re.IGNORECASE)
    if m:
        total = _to_number(m.group(1))

    line_items: list[LineItem] = []
    in_table = False
    for line in lines:
        if re.match(r"Description\s+Qty\s+Unit Price\s+Amount", line, re.IGNORECASE):
            in_table = True
            continue
        if in_table and re.match(r"(Subtotal|Tax|Total)\s*:", line, re.IGNORECASE):
            break
        if in_table:
            tokens = line.rsplit(maxsplit=3)
            if len(tokens) == 4:
                desc, qty_s, unit_s, amount_s = tokens
                qty = _to_number(qty_s)
                unit_price = _to_number(unit_s)
                amount = _to_number(amount_s)
                if qty is not None and unit_price is not None and amount is not None:
                    line_items.append(
                        {"description": desc.strip(), "qty": qty, "unit_price": unit_price, "amount": amount}
                    )

    found = sum(1 for f, v in [("vendor", vendor), ("invoice_num", invoice_num), ("date", date), ("total", total)] if v)
    confidence = found / len(REQUIRED_FIELDS)

    # Cross-check: subtotal + tax should equal total within 1%.
    # If they disagree the regex likely grabbed the wrong number — drop confidence
    # so Gemini or a human review catches it rather than auto-approving bad data.
    if subtotal is not None and tax is not None and total is not None and total > 0:
        # tax=0 is valid (zero-rated invoice); check still runs as long as all three were parsed
        if abs((subtotal + tax) - total) > total * 0.01:
            confidence = min(confidence, 0.6)

    # If any critical field is None, cap confidence to 0.4 so downstream always holds for review
    if vendor is None or total is None or invoice_num is None:
        confidence = min(confidence, 0.4)

    return {
        "vendor": vendor,
        "invoice_num": invoice_num,
        "date": date,
        "line_items": line_items,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "po_reference": po_reference,
        "extraction_confidence": round(confidence, 2),
        "extraction_method": "regex",
    }


def _gemini_extract(raw_text: str, gemini_key: Optional[str]) -> Optional[ExtractedFields]:
    if not gemini_key or not raw_text.strip():
        return None
    try:
        import google.generativeai as genai
    except ImportError:
        return None

    genai.configure(api_key=gemini_key, transport="rest")
    model = genai.GenerativeModel("gemini-3.8-flash")

    prompt = f"""Extract structured invoice fields from the raw OCR/text below.
Return ONLY a JSON object with these exact keys:
vendor (string or null), invoice_num (string or null), date (string or null),
line_items (list of {{description, qty, unit_price, amount}}), subtotal (number or null),
tax (number or null), total (number or null), po_reference (string or null).
Do not include markdown fences or commentary -- JSON only.

RAW TEXT:
---
{raw_text}
---
"""
    try:
        response = model.generate_content(prompt, request_options={"timeout": 12})
        text = response.text.strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
        parsed = json.loads(text)
    except Exception:
        return None

    found = sum(1 for f in REQUIRED_FIELDS if parsed.get(f))
    confidence = max(0.0, (found / len(REQUIRED_FIELDS)) - 0.15)  # dock confidence: assisted extraction on messy input

    return {
        "vendor": parsed.get("vendor"),
        "invoice_num": parsed.get("invoice_num"),
        "date": parsed.get("date"),
        "line_items": parsed.get("line_items") or [],
        "subtotal": parsed.get("subtotal"),
        "tax": parsed.get("tax"),
        "total": parsed.get("total"),
        "po_reference": parsed.get("po_reference"),
        "extraction_confidence": round(confidence, 2),
        "extraction_method": "gemini_assist",
    }


def extract_fields(
    raw_text: str,
    pdf_path: Optional[str | Path] = None,
    gemini_key: Optional[str] = None,
    source_confidence: float = 1.0,
) -> ExtractedFields:
    """source_confidence is the ingest-stage confidence (e.g. 0.4 for OCR'd
    text with no text layer). It scales down the final extraction_confidence
    so a clean-looking regex/Gemini parse of garbled OCR text never reports
    as fully trustworthy -- downstream decide.py treats low confidence as a
    reason to hold for human review rather than auto-approve."""
    regex_result = _regex_extract(raw_text)

    result = regex_result
    if regex_result["extraction_confidence"] < 0.75:
        gemini_result = _gemini_extract(raw_text, gemini_key)
        if gemini_result is not None and gemini_result["extraction_confidence"] > regex_result["extraction_confidence"]:
            result = gemini_result

    if source_confidence < 1.0:
        result["extraction_confidence"] = round(result["extraction_confidence"] * source_confidence, 2)

    return result

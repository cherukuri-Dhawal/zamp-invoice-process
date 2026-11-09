# Zamp ASA Case Study — PS-1 Invoice Processing

Automated invoice-to-decision pipeline: Ingest → Extract → Match → Validate → Decide.

## Setup
```
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
copy .env.example .env          # then add your real GEMINI_API_KEY
```

Tesseract OCR must be installed for scanned-PDF support (EC1):
- Windows: `winget install -e --id UB-Mannheim.TesseractOCR`
- Docker / Linux: handled automatically via `Dockerfile`

## Run
```
bash run.sh
```
Visit http://127.0.0.1:8000

## Demo run order

Run these in order for the cleanest demo. Click **Reset Demo** on the dashboard
between full runs to clear duplicate-detection history.

| # | Sample button label | Expected decision | What it shows |
|---|---|---|---|
| 1 | Happy path — Approve | **Approve** | All 5 rules pass, confidence 1.0 |
| 2 | EC1: Scanned PDF (OCR) | **Hold for Review** | OCR fallback, confidence 0.6 → below 0.8 threshold |
| 3 | EC2: Split PO part 1 | **Hold for Review** | Invoice under PO amount, possible split |
| 4 | EC2: Split PO part 2 | **Hold for Review** | Cumulative = 100% of PO, still needs confirmation |
| 5 | EC3a: Within tolerance | **Approve** | 2% over PO, within allowed band |
| 6 | EC3b: Outside tolerance | **Hold for Review** | 8% over PO, exceeds band |
| 7 | EC4a: Missing invoice number | **Hold for Review** | Completeness rule fails |
| 8 | EC4b: Unapproved vendor | **Reject** | Hard stop — vendor not on approved list |
| 9 | EC4c: Duplicate invoice | **Reject** | Same vendor + invoice# seen within 30 days |

## Assumptions log

### Decision thresholds
- **Amount tolerance**: each PO carries a `tolerance_pct` field (default 2%). Invoice total within ±tolerance% → pass. Over → Hold. Under → split-PO Hold.
- **Duplicate window**: same vendor + invoice number within **30 days** = duplicate → Reject.
- **Confidence threshold for auto-approve**: extraction confidence must be **≥ 0.8**. Below that, the decision is held for human review even if all business rules pass.
- **OCR confidence**: scanned PDFs (no text layer) set ingest confidence to **0.6**. This propagates into extraction confidence, keeping OCR'd invoices below the 0.8 auto-approve threshold.
- **Critical-field cap**: if vendor, total, or invoice_num is `None` after extraction, confidence is capped at **0.4**.
- **Subtotal+tax cross-check**: if `|subtotal + tax − total| > 1% of total`, confidence is capped at **0.6** (possible wrong number grabbed by regex).

### Business rules
- **Reject rules** (hard stops): unapproved vendor, closed PO, duplicate invoice.
- **Hold rules** (needs human): missing field, no PO match, amount outside tolerance, split PO pending, low confidence.
- **Approve**: all rules pass AND confidence ≥ 0.8.

### LLM usage
- Gemini is used **only** for extraction assist (parse messy text into structured JSON) when regex confidence < 0.75.
- Gemini **never** makes the approve/hold/reject decision — that is pure deterministic Python in `decide.py`.
- If Gemini is unreachable (network timeout, bad key), the pipeline falls back to regex-only extraction gracefully.

### Infrastructure
- **Database**: SQLite (`data/runs.db`). Ephemeral on Render free tier — resets on redeploy. Acceptable for demo; would use Postgres in production.
- **OCR engine**: Tesseract v5 via `pytesseract` + `pymupdf` for rasterisation. DPI set to 200 (not 300) to stay within Render's 512 MB RAM limit.
- **PO dataset**: static JSON file (`data/po_dataset.json`). In production this would be a database query.
- **Test invoices**: generated with `reportlab` + `pymupdf`. EC1 is a genuinely image-only PDF (no text layer embedded).

## Pipeline stages

| Stage | File | Description |
|---|---|---|
| Ingest | `app/ingest.py` | Extract text layer; OCR fallback if absent |
| Extract | `app/extract.py` | Regex-first; Gemini assist if confidence < 0.75 |
| Match | `app/match.py` | Vendor + PO reference lookup against dataset |
| Validate | `app/validate.py` | 5 deterministic business rules |
| Decide | `app/decide.py` | Approve / Hold for Review / Reject |

## Tests
```
pytest tests/ -v
```
Expected: **8 passed**.

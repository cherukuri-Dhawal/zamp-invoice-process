"""EC1 — scanned invoice, no text layer -> OCR fallback.

Proves ingest.py genuinely detects the missing text layer and falls back to
real Tesseract OCR (not faked), and that the pipeline flags lower confidence
on OCR'd fields rather than silently trusting garbled text -- per the spec's
explicit warning not to fake the hard part.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from tests.pipeline_helper import run_pipeline

INVOICE_PATH = Path(__file__).resolve().parent.parent / "data" / "test_invoices" / "12_ec1_scanned_nimbus.pdf"


def test_ec1_scanned_invoice_flags_low_confidence():
    db.init_db()
    db.reset_runs()  # isolate from any prior run with the same vendor+invoice#
    result = run_pipeline(INVOICE_PATH)

    print("\n=== EC1 STAGE LOG ===")
    print(json.dumps(result["stage_log"], indent=2))
    print("\n=== EC1 DECISION ===")
    print(json.dumps(result["decision_result"], indent=2))

    ingest_result = result["ingest"]
    extracted = result["extracted"]

    assert ingest_result["has_text_layer"] is False, "Scanned PDF should have no text layer"
    assert ingest_result["ocr_used"] is True, "OCR fallback should have run"
    assert ingest_result["confidence"] < 1.0, "OCR ingest confidence must be flagged lower than a clean text layer"

    # OCR should still recover the easy single-line fields despite noise
    assert extracted["vendor"] == "Nimbus Marketing Agency"
    assert extracted["invoice_num"] == "NM-204"
    assert extracted["po_reference"] == "PO-1009"

    # Extraction confidence must be visibly degraded, not silently trusted
    assert extracted["extraction_confidence"] < 0.8

    # Garbled table layout means total legitimately failed to parse -- the
    # pipeline should hold for a human rather than guess at the amount.
    assert result["decision_result"]["decision"] == "Hold for Review"


if __name__ == "__main__":
    test_ec1_scanned_invoice_flags_low_confidence()
    print("\nEC1 test PASSED.")

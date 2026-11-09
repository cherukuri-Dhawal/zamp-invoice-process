"""Shared pipeline runner for tests -- Ingest -> Extract -> Match -> Validate -> Decide,
with a full stage_log, used by both the happy-path test and every edge-case test so the
wiring is identical to what main.py will call in Phase 3's live run view."""
import os
import time
from pathlib import Path

from app import decide, extract, ingest, match, validate


def run_pipeline(invoice_path: Path, po_dataset: list[dict] | None = None) -> dict:
    stage_log = []

    def log_stage(stage: str, status: str, detail: str):
        stage_log.append({
            "stage": stage,
            "status": status,
            "detail": detail,
            "timestamp_ms": int(time.time() * 1000),
        })

    # Stage 1: Ingest
    ingest_result = ingest.ingest_pdf(invoice_path)
    log_stage(
        "ingest",
        "done" if ingest_result["has_text_layer"] else "flagged",
        f"page_count={ingest_result['page_count']}, has_text_layer={ingest_result['has_text_layer']}, "
        f"ocr_used={ingest_result['ocr_used']}, confidence={ingest_result['confidence']}",
    )

    # Stage 2: Extract
    gemini_key = os.getenv("GEMINI_API_KEY")
    extracted = extract.extract_fields(
        ingest_result["text"], invoice_path, gemini_key, source_confidence=ingest_result["confidence"] or 1.0
    )
    log_stage(
        "extract",
        "done",
        f"vendor={extracted['vendor']}, invoice_num={extracted['invoice_num']}, total={extracted['total']}, "
        f"method={extracted['extraction_method']}, confidence={extracted['extraction_confidence']}",
    )

    # Stage 3: Match
    if po_dataset is None:
        po_dataset = match.load_po_dataset()
    match_result = match.match_invoice_to_po(extracted, po_dataset)
    matched_po = match_result["matched_po"]
    log_stage(
        "match",
        "done" if matched_po else "flagged",
        f"match_type={match_result['match_type']}, matched_po={matched_po['po_number'] if matched_po else None}",
    )

    # Stage 4: Validate
    validation_result = validate.validate_against_po(extracted, matched_po)
    log_stage(
        "validate",
        "done" if validation_result["passed"] else "flagged",
        f"passed={validation_result['passed']}, rules_fired={len(validation_result['rules_fired'])}, "
        f"violations={len(validation_result['violations'])}",
    )

    # Stage 5: Decide
    decision_result = decide.decide(validation_result, matched_po, extracted["extraction_confidence"])
    log_stage(
        "decide",
        "done",
        f"decision={decision_result['decision']}, confidence={decision_result['confidence']}",
    )

    return {
        "ingest": ingest_result,
        "extracted": extracted,
        "match": match_result,
        "validation": validation_result,
        "decision_result": decision_result,
        "stage_log": stage_log,
    }

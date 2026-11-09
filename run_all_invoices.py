"""Run all 9 test invoices through the full pipeline and print detailed per-stage output.

Usage:  python run_all_invoices.py
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv()

from app import db
from app.ingest import ingest_pdf
from app.extract import extract_fields
from app.match import match_invoice_to_po, load_po_dataset
from app.validate import validate_against_po
from app.decide import decide

INVOICE_DIR = Path(__file__).resolve().parent / "data" / "test_invoices"

SCENARIOS = [
    {
        "file": "01_happy_path_acme.pdf",
        "scenario": "Happy path: clean PDF, exact PO match, all fields present",
        "expected": "Approve",
    },
    {
        "file": "03_ec1_scanned_invoice.pdf",
        "scenario": "EC1: Scanned/image-only PDF — no text layer, OCR fallback required",
        "expected": "Hold for Review",
    },
    {
        "file": "04_ec2_split_po_invoice1.pdf",
        "scenario": "EC2 Part 1: Split PO — first partial invoice (Rs.30,000 of Rs.62,000 PO)",
        "expected": "Hold for Review",
    },
    {
        "file": "05_ec2_split_po_invoice2.pdf",
        "scenario": "EC2 Part 2: Split PO — second partial invoice (cumulative Rs.62,000 = 100% of PO)",
        "expected": "Hold for Review",
    },
    {
        "file": "06_ec3_within_tolerance.pdf",
        "scenario": "EC3a: Amount 2% over PO (Rs.51,000 vs Rs.50,000) — within 2% tolerance",
        "expected": "Approve",
    },
    {
        "file": "07_ec3_outside_tolerance.pdf",
        "scenario": "EC3b: Amount 8% over PO (Rs.54,000 vs Rs.50,000) — outside 2% tolerance",
        "expected": "Hold for Review",
    },
    {
        "file": "08_ec4_missing_invoice_number.pdf",
        "scenario": "EC4a: Missing invoice number field",
        "expected": "Hold for Review",
    },
    {
        "file": "09_ec4_unapproved_vendor.pdf",
        "scenario": "EC4b: Vendor not on approved list (ShadySuppliers Inc)",
        "expected": "Reject",
    },
    {
        "file": "10_ec4_duplicate.pdf",
        "scenario": "EC4c: Duplicate of invoice 1 (same vendor + invoice# within 30 days)",
        "expected": "Reject",
    },
]

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
po_dataset = load_po_dataset()

SEP = "-" * 90


def run_one(filepath: Path) -> dict:
    stage_log = []

    ingest = ingest_pdf(filepath)
    stage_log.append({"stage": "ingest", "result": {k: v for k, v in ingest.items() if k != "text"}})

    extracted = extract_fields(
        ingest["text"],
        pdf_path=filepath,
        gemini_key=GEMINI_KEY,
        source_confidence=ingest["confidence"] if ingest["confidence"] > 0 else 1.0,
    )
    stage_log.append({"stage": "extract", "result": extracted})

    match = match_invoice_to_po(extracted, po_dataset)
    stage_log.append({"stage": "match", "result": {k: v for k, v in match.items() if k != "candidates"}})

    validation = validate_against_po(extracted, match["matched_po"])
    stage_log.append({"stage": "validate", "result": {"passed": validation["passed"], "violations": validation["violations"]}})

    decision_result = decide(validation, match["matched_po"], extracted["extraction_confidence"])
    stage_log.append({"stage": "decide", "result": decision_result})

    run_id = db.save_run(
        filename=filepath.name,
        extracted=extracted,
        matched_po=match["matched_po"],
        validation=validation,
        decision=decision_result["decision"],
        reasoning=decision_result["reasoning"],
        confidence=decision_result["confidence"],
        stage_log=stage_log,
    )

    return {
        "run_id": run_id,
        "ingest": ingest,
        "extracted": extracted,
        "match": match,
        "validation": validation,
        "decision_result": decision_result,
    }


def main():
    db.init_db()
    db.reset_runs()

    correct = 0
    wrong = []

    for i, scenario in enumerate(SCENARIOS, 1):
        filepath = INVOICE_DIR / scenario["file"]
        expected = scenario["expected"]

        print(SEP)
        print(f"INVOICE {i}/9: {scenario['file']}")
        print(f"Scenario: {scenario['scenario']}")
        print()

        if not filepath.exists():
            print(f"  ERROR: File not found: {filepath}")
            wrong.append(f"{scenario['file']} — file missing")
            continue

        result = run_one(filepath)
        ingest = result["ingest"]
        ext = result["extracted"]
        match = result["match"]
        val = result["validation"]
        dec = result["decision_result"]

        # Stage 1
        print("STAGE 1 - INGEST:")
        print(f"  Text layer: {'YES' if ingest['has_text_layer'] else 'NO'}")
        print(f"  OCR used:   {'YES' if ingest['ocr_used'] else 'NO'}")
        print(f"  Confidence: {ingest['confidence']}")

        # Stage 2
        print("\nSTAGE 2 - EXTRACT:")
        print(f"  Vendor:     {ext['vendor'] or 'MISSING'}")
        print(f"  Invoice #:  {ext['invoice_num'] or 'MISSING'}")
        print(f"  Total:      {ext['total'] or 'MISSING'}")
        print(f"  Confidence: {ext['extraction_confidence']}")
        print(f"  Method:     {ext['extraction_method']}")

        # Stage 3
        print("\nSTAGE 3 - MATCH:")
        po = match["matched_po"]
        print(f"  PO Matched: {po['po_number'] + ' (' + po['vendor_name'] + ')' if po else 'NONE'}")
        print(f"  Match type: {match['match_type']}")

        # Stage 4
        print("\nSTAGE 4 - VALIDATE:")
        rule_map = {r["rule"]: r for r in val["rules_fired"]}
        def rule_line(key: str, label: str, extra: str = "") -> str:
            r = rule_map.get(key)
            if r is None:
                return f"  {label}: N/A"
            status = "PASS" if r["status"] == "pass" else "FAIL"
            tail = f"  ({extra})" if extra else f"  ({r['detail']})" if r["status"] == "fail" else ""
            return f"  {label}: {status}{tail}"

        print(rule_line("completeness", "Completeness"))
        print(rule_line("approved_vendor", "Vendor approved"))
        print(rule_line("po_open", "PO open"))
        amt_rule = rule_map.get("amount_tolerance") or rule_map.get("split_po_pending")
        if amt_rule:
            status = "PASS" if amt_rule["status"] == "pass" else "FAIL"
            if po and ext.get("total") and po.get("po_amount"):
                delta_pct = (ext["total"] - po["po_amount"]) / po["po_amount"] * 100
                extra = f"{ext['total']:,.0f} vs {po['po_amount']:,.0f}, {delta_pct:+.1f}%"
            else:
                extra = amt_rule["detail"][:60]
            print(f"  Amount check: {status}  ({extra})")
        else:
            print("  Amount check: N/A")
        print(rule_line("duplicate_check", "Not duplicate"))

        # Stage 5
        print("\nSTAGE 5 - DECIDE:")
        print(f"  DECISION:   {dec['decision']}")
        print(f"  Confidence: {dec['confidence']}")
        print(f"  Reasoning:  {dec['reasoning']}")

        match_sym = "CORRECT" if dec["decision"] == expected else "*** WRONG ***"
        print(f"\nEXPECTED: {expected}")
        print(f"MATCH:    {match_sym}")

        if dec["decision"] == expected:
            correct += 1
        else:
            wrong.append(f"{scenario['file']} — expected {expected}, got {dec['decision']}")

    print("\n" + "=" * 90)
    print("=== SUMMARY ===")
    print(f"Total invoices:   9")
    print(f"Correct decisions: {correct}/9")
    if wrong:
        print("Wrong decisions:")
        for w in wrong:
            print(f"  - {w}")
    else:
        print("Wrong decisions: none")
    status = "ALL PASS" if correct == 9 else "NEEDS FIX"
    print(f"Status: {status}")
    print("=" * 90)


if __name__ == "__main__":
    main()

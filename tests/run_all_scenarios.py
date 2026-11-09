"""Phase 4 demo script: run the full pipeline over happy path + all edge cases,
in sequence, saving each to SQLite so stateful checks (duplicate detection,
split-PO cumulative tracking) see prior runs exactly like a real multi-invoice
intake would. Prints one consolidated table plus full per-invoice detail.

Not a pytest file -- this is for manual/visual review of pipeline behavior
across every scenario in one pass. See tests/test_ec*.py for the pass/fail
assertions pytest checks.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from app import db
from tests.pipeline_helper import run_pipeline

load_dotenv()

INVOICE_DIR = Path(__file__).resolve().parent.parent / "data" / "test_invoices"

# Sequence requested: happy path, EC1 (scanned), EC2 (split PO x2), EC3 (within
# then outside tolerance), EC4 (missing invoice#, unapproved vendor), then the
# happy-path invoice again to exercise duplicate detection.
SCENARIOS = [
    ("01_happy_path_acme.pdf", "Happy path: clean PDF, explicit PO, exact match"),
    ("12_ec1_scanned_nimbus.pdf", "EC1: scanned PDF, no text layer -> OCR fallback"),
    ("10_ec2_split_po_pinecrest_part1.pdf", "EC2: split-PO invoice 1/2"),
    ("11_ec2_split_po_pinecrest_part2.pdf", "EC2: split-PO invoice 2/2 (cumulative == PO amount)"),
    ("04_ec3_within_tolerance_crestline.pdf", "EC3a: 1.5% over PO (within 2% tolerance)"),
    ("05_ec3_outside_tolerance_stratos.pdf", "EC3b: 8% over PO (outside 2% tolerance)"),
    ("07_ec4a_missing_invoice_number_meridian.pdf", "EC4a: missing invoice number"),
    ("06_ec4b_unapproved_vendor_summit.pdf", "EC4b: vendor not on approved list"),
    ("01_happy_path_acme.pdf", "EC4c: re-submit happy-path invoice -> duplicate detection"),
]


def main():
    db.init_db()
    db.reset_runs()

    rows = []
    details = []

    for idx, (filename, scenario) in enumerate(SCENARIOS, start=1):
        path = INVOICE_DIR / filename
        result = run_pipeline(path)
        decision_result = result["decision_result"]
        matched_po = result["match"]["matched_po"]

        run_id = db.save_run(
            filename=filename,
            extracted=result["extracted"],
            matched_po=matched_po,
            validation=result["validation"],
            decision=decision_result["decision"],
            reasoning=decision_result["reasoning"],
            confidence=decision_result["confidence"],
            stage_log=result["stage_log"],
        )

        rows.append({
            "seq": idx,
            "run_id": run_id,
            "filename": filename,
            "scenario": scenario,
            "matched_po": matched_po["po_number"] if matched_po else None,
            "match_type": result["match"]["match_type"],
            "extraction_conf": result["extracted"]["extraction_confidence"],
            "ocr_used": result["ingest"]["ocr_used"],
            "decision": decision_result["decision"],
            "decision_conf": decision_result["confidence"],
        })
        details.append((idx, filename, scenario, result))

    # --- Consolidated table ---
    print("\n" + "=" * 140)
    print("CONSOLIDATED RESULTS TABLE")
    print("=" * 140)
    header = f"{'#':<3}{'run_id':<7}{'filename':<42}{'matched_po':<12}{'match_type':<11}{'extr_conf':<10}{'ocr':<6}{'DECISION':<18}{'dec_conf':<9}"
    print(header)
    print("-" * 140)
    for r in rows:
        print(
            f"{r['seq']:<3}{r['run_id']:<7}{r['filename']:<42}{str(r['matched_po']):<12}"
            f"{r['match_type']:<11}{r['extraction_conf']:<10}{str(r['ocr_used']):<6}"
            f"{r['decision']:<18}{r['decision_conf']:<9}"
        )
    print("=" * 140)

    # --- Full per-invoice detail ---
    for idx, filename, scenario, result in details:
        print(f"\n{'#' * 100}")
        print(f"# [{idx}] {filename} -- {scenario}")
        print(f"{'#' * 100}")
        print("\n--- STAGE LOG ---")
        print(json.dumps(result["stage_log"], indent=2))
        print("\n--- EXTRACTED FIELDS ---")
        print(json.dumps(result["extracted"], indent=2))
        print("\n--- MATCH ---")
        print(json.dumps(
            {"match_type": result["match"]["match_type"],
             "matched_po": result["match"]["matched_po"],
             "candidates": [c["po_number"] for c in result["match"]["candidates"]]},
            indent=2,
        ))
        print("\n--- VALIDATION ---")
        print(json.dumps(result["validation"], indent=2))
        print("\n--- DECISION ---")
        print(json.dumps(result["decision_result"], indent=2))


if __name__ == "__main__":
    main()

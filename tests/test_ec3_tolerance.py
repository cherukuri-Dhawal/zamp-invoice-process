"""EC3 — amount mismatch, within vs. outside tolerance.

06_ec3 invoice is 1.5% over its PO (within the 2% tolerance) -> auto-approve.
05_ec3 invoice is 8% over its PO (outside tolerance) -> hold, with the exact
delta shown in the reasoning.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from tests.pipeline_helper import run_pipeline

INVOICE_DIR = Path(__file__).resolve().parent.parent / "data" / "test_invoices"
WITHIN = INVOICE_DIR / "04_ec3_within_tolerance_crestline.pdf"
OUTSIDE = INVOICE_DIR / "05_ec3_outside_tolerance_stratos.pdf"


def test_ec3a_within_tolerance_approves():
    db.init_db()
    db.reset_runs()
    result = run_pipeline(WITHIN)

    print("\n=== EC3a (within tolerance) STAGE LOG ===")
    print(json.dumps(result["stage_log"], indent=2))
    print("\n=== EC3a DECISION ===")
    print(json.dumps(result["decision_result"], indent=2))

    assert result["decision_result"]["decision"] == "Approve"
    tolerance_rule = next(r for r in result["validation"]["rules_fired"] if r["rule"] == "amount_tolerance")
    assert tolerance_rule["status"] == "pass"
    assert "1.50%" in tolerance_rule["detail"]


def test_ec3b_outside_tolerance_holds():
    db.init_db()
    db.reset_runs()
    result = run_pipeline(OUTSIDE)

    print("\n=== EC3b (outside tolerance) STAGE LOG ===")
    print(json.dumps(result["stage_log"], indent=2))
    print("\n=== EC3b DECISION ===")
    print(json.dumps(result["decision_result"], indent=2))

    assert result["decision_result"]["decision"] == "Hold for Review"
    assert "8% over PO limit" in result["decision_result"]["reasoning"]
    assert "Within tolerance: 2%" in result["decision_result"]["reasoning"]


if __name__ == "__main__":
    test_ec3a_within_tolerance_approves()
    test_ec3b_outside_tolerance_holds()
    print("\nEC3 tests PASSED.")

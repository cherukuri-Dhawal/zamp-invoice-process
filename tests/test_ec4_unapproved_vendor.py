"""EC4b — vendor is not on the approved list -> auto-reject with reason."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from tests.pipeline_helper import run_pipeline

INVOICE_PATH = Path(__file__).resolve().parent.parent / "data" / "test_invoices" / "06_ec4b_unapproved_vendor_summit.pdf"


def test_ec4b_unapproved_vendor_rejects():
    db.init_db()
    db.reset_runs()
    result = run_pipeline(INVOICE_PATH)

    print("\n=== EC4b STAGE LOG ===")
    print(json.dumps(result["stage_log"], indent=2))
    print("\n=== EC4b DECISION ===")
    print(json.dumps(result["decision_result"], indent=2))

    assert result["match"]["matched_po"]["approved"] is False
    assert result["decision_result"]["decision"] == "Reject"
    assert "not on the approved vendor list" in result["decision_result"]["reasoning"].lower()


if __name__ == "__main__":
    test_ec4b_unapproved_vendor_rejects()
    print("\nEC4b test PASSED.")

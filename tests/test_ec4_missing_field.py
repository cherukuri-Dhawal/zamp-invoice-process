"""EC4a — invoice has no invoice number. The process should hold and state
exactly what's missing, rather than silently guessing one."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from tests.pipeline_helper import run_pipeline

INVOICE_PATH = Path(__file__).resolve().parent.parent / "data" / "test_invoices" / "07_ec4a_missing_invoice_number_meridian.pdf"


def test_ec4a_missing_invoice_number_holds():
    db.init_db()
    db.reset_runs()
    result = run_pipeline(INVOICE_PATH)

    print("\n=== EC4a STAGE LOG ===")
    print(json.dumps(result["stage_log"], indent=2))
    print("\n=== EC4a DECISION ===")
    print(json.dumps(result["decision_result"], indent=2))

    assert result["extracted"]["invoice_num"] is None
    assert result["decision_result"]["decision"] == "Hold for Review"
    assert "invoice number" in result["decision_result"]["reasoning"]


if __name__ == "__main__":
    test_ec4a_missing_invoice_number_holds()
    print("\nEC4a test PASSED.")

"""EC4c — the same invoice number + vendor is submitted twice. The duplicate
detector should catch the second submission."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from tests.pipeline_helper import run_pipeline

INVOICE_DIR = Path(__file__).resolve().parent.parent / "data" / "test_invoices"
FIRST = INVOICE_DIR / "08_ec4c_duplicate_falcon_A.pdf"
SECOND = INVOICE_DIR / "09_ec4c_duplicate_falcon_B.pdf"


def _save(path: Path, result: dict) -> int:
    return db.save_run(
        filename=path.name,
        extracted=result["extracted"],
        matched_po=result["match"]["matched_po"],
        validation=result["validation"],
        decision=result["decision_result"]["decision"],
        reasoning=result["decision_result"]["reasoning"],
        confidence=result["decision_result"]["confidence"],
        stage_log=result["stage_log"],
    )


def test_ec4c_duplicate_invoice_rejects_second_submission():
    db.init_db()
    db.reset_runs()

    result1 = run_pipeline(FIRST)
    print("\n=== EC4c FIRST SUBMISSION DECISION ===")
    print(json.dumps(result1["decision_result"], indent=2))
    run_id_1 = _save(FIRST, result1)
    assert result1["decision_result"]["decision"] == "Approve"

    result2 = run_pipeline(SECOND)
    print("\n=== EC4c DUPLICATE SUBMISSION STAGE LOG ===")
    print(json.dumps(result2["stage_log"], indent=2))
    print("\n=== EC4c DUPLICATE SUBMISSION DECISION ===")
    print(json.dumps(result2["decision_result"], indent=2))

    assert result2["decision_result"]["decision"] == "Reject"
    assert "Duplicate invoice detected" in result2["decision_result"]["reasoning"]
    assert f"run #{run_id_1}" in result2["decision_result"]["reasoning"]


if __name__ == "__main__":
    test_ec4c_duplicate_invoice_rejects_second_submission()
    print("\nEC4c test PASSED.")

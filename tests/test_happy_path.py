"""Phase 2: prove the happy-path pipeline runs end-to-end.

Ingest -> Extract -> Match -> Validate -> Decide, for one clean invoice,
with a full stage log printed and the run persisted to SQLite.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

from app import db
from tests.pipeline_helper import run_pipeline

load_dotenv()

INVOICE_PATH = Path(__file__).resolve().parent.parent / "data" / "test_invoices" / "01_happy_path_acme.pdf"


def test_happy_path_approves():
    db.init_db()
    db.reset_runs()
    result = run_pipeline(INVOICE_PATH)

    print("\n=== STAGE LOG ===")
    print(json.dumps(result["stage_log"], indent=2))
    print("\n=== FINAL DECISION ===")
    print(json.dumps(result["decision_result"], indent=2))

    run_id = db.save_run(
        filename=INVOICE_PATH.name,
        extracted=result["extracted"],
        matched_po=result["match"]["matched_po"],
        validation=result["validation"],
        decision=result["decision_result"]["decision"],
        reasoning=result["decision_result"]["reasoning"],
        confidence=result["decision_result"]["confidence"],
        stage_log=result["stage_log"],
    )
    print(f"\n=== SAVED RUN id={run_id} ===")

    assert result["decision_result"]["decision"] == "Approve", (
        f"Expected Approve on happy path, got {result['decision_result']['decision']}: "
        f"{result['decision_result']['reasoning']}"
    )


if __name__ == "__main__":
    test_happy_path_approves()
    print("\nHappy path test PASSED.")

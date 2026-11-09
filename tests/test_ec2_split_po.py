"""EC2 — a vendor splits one PO across two partial invoices.

match.py must match both partials against the same PO (not reject them as
mismatches), and validate.py must track cumulative total across prior runs
against that PO. Both invoices hold for review: the first because its total
alone doesn't match the PO amount and no partner invoice is on record yet,
the second because together they exactly complete the PO -- and the system
still wants a human to confirm no further partials are coming.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from tests.pipeline_helper import run_pipeline

INVOICE_DIR = Path(__file__).resolve().parent.parent / "data" / "test_invoices"
PART1 = INVOICE_DIR / "10_ec2_split_po_pinecrest_part1.pdf"
PART2 = INVOICE_DIR / "11_ec2_split_po_pinecrest_part2.pdf"


def test_ec2_split_po_both_hold():
    db.init_db()
    db.reset_runs()  # deterministic: no prior runs against PO-1008

    result1 = run_pipeline(PART1)
    print("\n=== EC2 PART 1 STAGE LOG ===")
    print(json.dumps(result1["stage_log"], indent=2))
    print("\n=== EC2 PART 1 DECISION ===")
    print(json.dumps(result1["decision_result"], indent=2))

    run_id_1 = db.save_run(
        filename=PART1.name,
        extracted=result1["extracted"],
        matched_po=result1["match"]["matched_po"],
        validation=result1["validation"],
        decision=result1["decision_result"]["decision"],
        reasoning=result1["decision_result"]["reasoning"],
        confidence=result1["decision_result"]["confidence"],
        stage_log=result1["stage_log"],
    )

    result2 = run_pipeline(PART2)
    print("\n=== EC2 PART 2 STAGE LOG ===")
    print(json.dumps(result2["stage_log"], indent=2))
    print("\n=== EC2 PART 2 DECISION ===")
    print(json.dumps(result2["decision_result"], indent=2))

    # Both partials must match the same PO, not be rejected as mismatches
    assert result1["match"]["matched_po"]["po_number"] == "PO-1008"
    assert result2["match"]["matched_po"]["po_number"] == "PO-1008"

    assert result1["decision_result"]["decision"] == "Hold for Review"
    assert result2["decision_result"]["decision"] == "Hold for Review"

    split_rule_1 = next(r for r in result1["validation"]["violations"] if r["rule"] == "split_po_pending")
    split_rule_2 = next(r for r in result2["validation"]["violations"] if r["rule"] == "split_po_pending")

    assert "no prior partial invoices" in split_rule_1["detail"]
    assert f"run #{run_id_1}" not in split_rule_2["detail"]  # we reference count, not run id, but cumulative must be present
    assert "cumulative is 310,000.00" in split_rule_2["detail"]
    assert "0.00% off PO amount" in split_rule_2["detail"]


if __name__ == "__main__":
    test_ec2_split_po_both_hold()
    print("\nEC2 test PASSED.")

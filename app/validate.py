"""Stage 4: Validate — deterministic business rules against the matched PO.

Every rule is plain Python, not an LLM call. Each rule produces a record in
rules_fired (pass or fail); violations is the fail subset. decide.py reads
this structured result -- it is the only thing allowed to turn it into a
final decision.
"""
from typing import Literal, Optional, TypedDict

from app import db

REQUIRED_FIELDS = ("vendor", "invoice_num", "date", "total")
FIELD_LABELS = {"vendor": "vendor", "invoice_num": "invoice number", "date": "date", "total": "total"}

Severity = Literal["critical", "warning"]


class RuleResult(TypedDict):
    rule: str
    status: Literal["pass", "fail"]
    severity: Severity
    detail: str


class ValidationResult(TypedDict):
    passed: bool
    rules_fired: list[RuleResult]
    violations: list[RuleResult]
    confidence: float


def validate_against_po(extracted_invoice: dict, matched_po: Optional[dict]) -> ValidationResult:
    rules: list[RuleResult] = []

    # Rule: completeness — all required fields present
    missing = [f for f in REQUIRED_FIELDS if not extracted_invoice.get(f)]
    if missing:
        rules.append({
            "rule": "completeness",
            "status": "fail",
            "severity": "critical",
            "detail": f"Missing required field(s): {', '.join(FIELD_LABELS[f] for f in missing)}",
        })
    else:
        rules.append({
            "rule": "completeness",
            "status": "pass",
            "severity": "critical",
            "detail": "All required fields present (vendor, invoice_num, date, total).",
        })

    if matched_po is None:
        rules.append({
            "rule": "po_match",
            "status": "fail",
            "severity": "critical",
            "detail": "No matching purchase order found.",
        })
        violations = [r for r in rules if r["status"] == "fail"]
        return {
            "passed": False,
            "rules_fired": rules,
            "violations": violations,
            "confidence": 0.0,
        }

    # Rule: approved vendor
    if matched_po.get("approved"):
        rules.append({
            "rule": "approved_vendor",
            "status": "pass",
            "severity": "critical",
            "detail": f"Vendor '{matched_po['vendor_name']}' is on the approved vendor list.",
        })
    else:
        rules.append({
            "rule": "approved_vendor",
            "status": "fail",
            "severity": "critical",
            "detail": f"Vendor '{matched_po['vendor_name']}' is NOT on the approved vendor list.",
        })

    # Rule: PO is open
    if matched_po.get("status") == "open":
        rules.append({
            "rule": "po_open",
            "status": "pass",
            "severity": "critical",
            "detail": f"PO {matched_po['po_number']} is open.",
        })
    else:
        rules.append({
            "rule": "po_open",
            "status": "fail",
            "severity": "critical",
            "detail": f"PO {matched_po['po_number']} is '{matched_po.get('status')}', not open.",
        })

    # Rule: amount within tolerance (over-budget) vs. split-PO (under-budget)
    total = extracted_invoice.get("total")
    po_amount = matched_po.get("po_amount")
    tolerance_pct = matched_po.get("tolerance_pct", 0.0)
    if total is not None and po_amount:
        signed_delta_pct = (total - po_amount) / po_amount * 100
        abs_delta_pct = abs(signed_delta_pct)
        if abs_delta_pct <= tolerance_pct:
            rules.append({
                "rule": "amount_tolerance",
                "status": "pass",
                "severity": "warning",
                "detail": f"Invoice total {total:,.2f} is within {tolerance_pct}% tolerance of PO amount {po_amount:,.2f} (delta {abs_delta_pct:.2f}%).",
            })
        elif signed_delta_pct > tolerance_pct:
            rules.append({
                "rule": "amount_tolerance",
                "status": "fail",
                "severity": "warning",
                "detail": (
                    f"Amount is {signed_delta_pct:.0f}% over PO limit. Within tolerance: {tolerance_pct:.0f}%. "
                    f"(Invoice total {total:,.2f} vs PO amount {po_amount:,.2f}.)"
                ),
            })
        else:
            # Invoice total is under the PO amount by more than tolerance --
            # plausibly a partial invoice against a PO that's being split
            # across multiple invoices (EC2), not an error on its own.
            prior_runs = db.get_runs_by_po(matched_po["po_number"])
            prior_total = sum(
                (r.get("extracted_json") or {}).get("total", 0) or 0 for r in prior_runs
            )
            cumulative = prior_total + total
            cumulative_delta_pct = abs(cumulative - po_amount) / po_amount * 100
            if prior_runs:
                detail = (
                    f"Split PO detected: invoice total {total:,.2f} alone is {abs_delta_pct:.2f}% under PO "
                    f"amount {po_amount:,.2f} (PO {matched_po['po_number']}). Combined with {len(prior_runs)} "
                    f"prior invoice(s) against this PO ({prior_total:,.2f}), cumulative is {cumulative:,.2f} "
                    f"({cumulative_delta_pct:.2f}% off PO amount). Holding pending confirmation that all "
                    f"partial invoices for this PO have been received."
                )
            else:
                detail = (
                    f"Split PO detected, second invoice awaiting total verification: invoice total "
                    f"{total:,.2f} is {abs_delta_pct:.2f}% under PO amount {po_amount:,.2f} (PO "
                    f"{matched_po['po_number']}) with no prior partial invoices on record yet. Holding in "
                    f"case this is one part of a PO split across multiple invoices."
                )
            rules.append({
                "rule": "split_po_pending",
                "status": "fail",
                "severity": "warning",
                "detail": detail,
            })
    else:
        rules.append({
            "rule": "amount_tolerance",
            "status": "fail",
            "severity": "critical",
            "detail": "Cannot evaluate amount tolerance: invoice total or PO amount missing.",
        })

    # Rule: duplicate submission (same vendor + invoice number seen before)
    dup = db.find_duplicate_run(extracted_invoice.get("vendor"), extracted_invoice.get("invoice_num"))
    if dup:
        rules.append({
            "rule": "duplicate_check",
            "status": "fail",
            "severity": "critical",
            "detail": (
                f"Duplicate invoice detected (previously processed as run #{dup['id']}, "
                f"decision={dup.get('decision')})."
            ),
        })
    else:
        rules.append({
            "rule": "duplicate_check",
            "status": "pass",
            "severity": "critical",
            "detail": "No prior run found with this vendor + invoice number.",
        })

    violations = [r for r in rules if r["status"] == "fail"]
    passed = len(violations) == 0
    confidence = round(sum(1 for r in rules if r["status"] == "pass") / len(rules), 2)

    return {
        "passed": passed,
        "rules_fired": rules,
        "violations": violations,
        "confidence": confidence,
    }

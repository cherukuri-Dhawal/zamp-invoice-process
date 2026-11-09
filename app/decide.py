"""Stage 5: Decide — Approve / Hold for Review / Reject + plain-English reasoning.

Decision logic here is plain deterministic Python (if/else business rules).
Gemini is never asked "should this be approved?" -- it has no role in this
module at all. This function only consumes the structured output of
validate.py and produces a decision + a templated explanation.
"""
from typing import Literal, TypedDict

Decision = Literal["Approve", "Hold for Review", "Reject"]

# Rules whose failure is a hard stop -- no amount of review changes the
# outcome, so we reject outright rather than holding for a human to re-check.
REJECT_RULES = {"approved_vendor", "po_open", "duplicate_check", "currency_match"}

# Rules whose failure needs a human to supply missing info or make a judgment
# call, but isn't an automatic rejection.
HOLD_RULES = {"completeness", "po_match", "amount_tolerance", "split_po_pending"}

LOW_CONFIDENCE_THRESHOLD = 0.8


class DecisionResult(TypedDict):
    decision: Decision
    reasoning: str
    confidence: float


def _rule_detail(violations: list, rules_fired: list, rule_name: str) -> str:
    for r in violations + rules_fired:
        if r["rule"] == rule_name:
            return r["detail"]
    return ""


def decide(validation_results: dict, matched_po: dict | None, extraction_confidence: float) -> DecisionResult:
    violations = validation_results.get("violations", [])
    rules_fired = validation_results.get("rules_fired", [])
    validation_confidence = validation_results.get("confidence", 0.0)

    reject_hits = [v for v in violations if v["rule"] in REJECT_RULES]
    hold_hits = [v for v in violations if v["rule"] in HOLD_RULES]

    overall_confidence = round((validation_confidence + extraction_confidence) / 2, 2)
    po_number = matched_po["po_number"] if matched_po else "unknown"

    if reject_hits:
        # Order: duplicate > currency_match > approved_vendor > po_open (most common first)
        priority = ["duplicate_check", "currency_match", "approved_vendor", "po_open"]
        ordered = sorted(reject_hits, key=lambda r: priority.index(r["rule"]) if r["rule"] in priority else 99)
        reasons = "; ".join(r["detail"] for r in ordered)
        return {
            "decision": "Reject",
            "reasoning": f"Rejected — {reasons}",
            "confidence": overall_confidence,
        }

    if hold_hits:
        reasons = "; ".join(r["detail"] for r in hold_hits)
        return {
            "decision": "Hold for Review",
            "reasoning": f"Held for review — {reasons}",
            "confidence": overall_confidence,
        }

    if extraction_confidence < LOW_CONFIDENCE_THRESHOLD:
        return {
            "decision": "Hold for Review",
            "reasoning": (
                f"All {len(rules_fired)} validation rules passed against {po_number}, "
                f"but field extraction confidence is {extraction_confidence:.2f} "
                f"(threshold {LOW_CONFIDENCE_THRESHOLD}). A human should confirm extracted "
                "values before approval."
            ),
            "confidence": overall_confidence,
        }

    passed_rules = [r["rule"] for r in rules_fired if r["status"] == "pass"]
    return {
        "decision": "Approve",
        "reasoning": (
            f"Approved against {po_number}. "
            f"All {len(passed_rules)} rules passed: {', '.join(passed_rules)}. "
            f"Extraction confidence: {extraction_confidence:.2f}."
        ),
        "confidence": overall_confidence,
    }

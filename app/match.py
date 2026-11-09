"""Stage 3: Match — match extracted invoice fields against the PO dataset.

Matching is deterministic: vendor name (normalized, fuzzy-ish via substring/
casefold) plus an explicit PO reference match. Falls back to vendor-only
matching when no PO reference was extracted (implied-PO case), which can
produce an "ambiguous" result if more than one open PO fits.
"""
import json
from pathlib import Path
from typing import Literal, Optional, TypedDict

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PO_DATASET_PATH = DATA_DIR / "po_dataset.json"

MatchType = Literal["exact", "partial", "ambiguous", "none", "split_po_overflow"]


class MatchResult(TypedDict):
    matched_po: Optional[dict]
    candidates: list[dict]
    match_type: MatchType


def load_po_dataset(path: Path = PO_DATASET_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _normalize(s: Optional[str]) -> str:
    return (s or "").strip().casefold()


def _vendor_matches(extracted_vendor: Optional[str], po_vendor: str) -> bool:
    ev = _normalize(extracted_vendor)
    pv = _normalize(po_vendor)
    if not ev:
        return False
    return ev == pv or ev in pv or pv in ev


def match_invoice_to_po(extracted_fields: dict, po_dataset: Optional[list[dict]] = None) -> MatchResult:
    if po_dataset is None:
        po_dataset = load_po_dataset()

    vendor = extracted_fields.get("vendor")
    po_reference = extracted_fields.get("po_reference")

    vendor_candidates = [po for po in po_dataset if _vendor_matches(vendor, po["vendor_name"])]

    if po_reference:
        exact = [po for po in vendor_candidates if _normalize(po["po_number"]) == _normalize(po_reference)]
        if exact:
            return {"matched_po": exact[0], "candidates": exact, "match_type": "exact"}
        # PO reference given but didn't match any vendor-matching PO -- try
        # matching the reference alone, in case vendor name extraction was off.
        ref_only = [po for po in po_dataset if _normalize(po["po_number"]) == _normalize(po_reference)]
        if ref_only:
            return {"matched_po": ref_only[0], "candidates": ref_only, "match_type": "partial"}

    if len(vendor_candidates) == 1:
        return {"matched_po": vendor_candidates[0], "candidates": vendor_candidates, "match_type": "partial"}

    if len(vendor_candidates) > 1:
        return {"matched_po": None, "candidates": vendor_candidates, "match_type": "ambiguous"}

    return {"matched_po": None, "candidates": [], "match_type": "none"}

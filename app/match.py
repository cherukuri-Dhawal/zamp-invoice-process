"""Stage 3: Match — match extracted invoice fields against the PO dataset.

Primary path: exact PO reference match. Fallback: fuzzy vendor name match
using rapidfuzz token_sort_ratio with an 85% threshold. If multiple vendors
score within 3 points of the best match, result is "ambiguous".

# OPTIONAL UPGRADE (not implemented): embedding similarity for semantic matching
# from sentence_transformers import SentenceTransformer
# model = SentenceTransformer('all-MiniLM-L6-v2')
# similarities = cosine_similarity([model.encode(vendor)], [model.encode(po['vendor_name']) for po in po_dataset])
"""
import json
import re
from pathlib import Path
from typing import Literal, Optional, TypedDict

from rapidfuzz import fuzz

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PO_DATASET_PATH = DATA_DIR / "po_dataset.json"

FUZZY_THRESHOLD = 85

MatchType = Literal["exact", "partial", "ambiguous", "none", "split_po_overflow"]


class MatchResult(TypedDict):
    matched_po: Optional[dict]
    candidates: list[dict]
    match_type: MatchType


def load_po_dataset(path: Path = PO_DATASET_PATH) -> list[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


_COMPANY_SUFFIXES = re.compile(
    r"\b(inc|incorporated|ltd|limited|llc|llp|corp|corporation|co|company|pvt|private)\b\.?$",
    re.IGNORECASE,
)


def _normalize(s: Optional[str]) -> str:
    if not s:
        return ""
    # Strip punctuation, collapse whitespace, lowercase
    s = s.strip().casefold()
    # Remove trailing company suffixes ("Acme Inc." → "acme", "Global Parts Co" → "global parts")
    s = _COMPANY_SUFFIXES.sub("", s).strip().rstrip(",. ")
    return s


def _fuzzy_vendor_score(extracted_vendor: Optional[str], po_vendor: str) -> float:
    ev = _normalize(extracted_vendor)
    pv = _normalize(po_vendor)
    if not ev:
        return 0.0
    # Exact substring match → treat as 100 so existing tests are unaffected
    if ev == pv or ev in pv or pv in ev:
        return 100.0
    return fuzz.token_sort_ratio(ev, pv)


def match_invoice_to_po(extracted_fields: dict, po_dataset: Optional[list[dict]] = None) -> MatchResult:
    if po_dataset is None:
        po_dataset = load_po_dataset()

    vendor = extracted_fields.get("vendor")
    po_reference = extracted_fields.get("po_reference")

    # --- Exact PO reference match (highest confidence) ---
    if po_reference:
        ref_norm = _normalize(po_reference)
        ref_matches = [po for po in po_dataset if _normalize(po["po_number"]) == ref_norm]
        if ref_matches:
            return {"matched_po": ref_matches[0], "candidates": ref_matches, "match_type": "exact"}

    # --- Fuzzy vendor name match ---
    scored = [(po, _fuzzy_vendor_score(vendor, po["vendor_name"])) for po in po_dataset]
    above_threshold = [(po, score) for po, score in scored if score >= FUZZY_THRESHOLD]

    if not above_threshold:
        return {"matched_po": None, "candidates": [], "match_type": "none"}

    above_threshold.sort(key=lambda x: x[1], reverse=True)
    best_score = above_threshold[0][1]

    # If multiple candidates score within 3 points of the best → ambiguous
    top_candidates = [po for po, score in above_threshold if best_score - score <= 3]
    if len(top_candidates) > 1:
        return {"matched_po": None, "candidates": top_candidates, "match_type": "ambiguous"}

    return {"matched_po": top_candidates[0], "candidates": top_candidates, "match_type": "partial"}

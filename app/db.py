"""SQLite schema and query helpers for run history / audit trail."""
import json
import sqlite3
from pathlib import Path
from typing import Any, Optional

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "runs.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uploaded_filename TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    extracted_json TEXT,
    matched_po_number TEXT,
    validation_results_json TEXT,
    decision TEXT,
    decision_reasoning TEXT,
    confidence REAL,
    stage_log_json TEXT
);
"""


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.execute(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def create_run(uploaded_filename: str, timestamp: str) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO runs (uploaded_filename, timestamp) VALUES (?, ?)",
            (uploaded_filename, timestamp),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_run(run_id: int, **fields: Any) -> None:
    """Update arbitrary columns on a run. JSON-serializable values under
    *_json-suffixed keys are expected to already be dict/list and get
    serialized here."""
    if not fields:
        return
    json_cols = {"extracted_json", "validation_results_json", "stage_log_json"}
    set_clauses = []
    values = []
    for key, value in fields.items():
        if key in json_cols and not isinstance(value, str):
            value = json.dumps(value)
        set_clauses.append(f"{key} = ?")
        values.append(value)
    values.append(run_id)
    conn = get_conn()
    try:
        conn.execute(
            f"UPDATE runs SET {', '.join(set_clauses)} WHERE id = ?", values
        )
        conn.commit()
    finally:
        conn.close()


def save_run(
    filename: str,
    extracted: dict,
    matched_po: Optional[dict],
    validation: dict,
    decision: str,
    reasoning: str,
    confidence: float,
    stage_log: list,
) -> int:
    """Create and populate a run row in one call; returns the run id."""
    from datetime import datetime, timezone

    run_id = create_run(filename, datetime.now(timezone.utc).isoformat())
    update_run(
        run_id,
        extracted_json=extracted,
        matched_po_number=matched_po["po_number"] if matched_po else None,
        validation_results_json=validation,
        decision=decision,
        decision_reasoning=reasoning,
        confidence=confidence,
        stage_log_json=stage_log,
    )
    return run_id


def reset_runs() -> None:
    """Wipe all run history. Used by tests that need deterministic state for
    duplicate-detection / split-PO cumulative checks."""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM runs")
        conn.commit()
    finally:
        conn.close()


def get_runs_by_po(po_number: str) -> list[dict]:
    """All previously processed runs matched to a given PO number, oldest first.
    Used by validate.py to detect split-PO (partial invoice) scenarios."""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM runs WHERE matched_po_number = ? ORDER BY id ASC", (po_number,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def find_duplicate_run(
    vendor: Optional[str], invoice_num: Optional[str], within_days: int = 30
) -> Optional[dict]:
    """Look for a prior run with the same vendor + invoice number within the
    lookback window. Returns the most recent match, or None."""
    if not vendor or not invoice_num:
        return None

    from datetime import datetime, timedelta, timezone

    cutoff = datetime.now(timezone.utc) - timedelta(days=within_days)
    conn = get_conn()
    try:
        rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
    finally:
        conn.close()

    for row in rows:
        d = _row_to_dict(row)
        extracted = d.get("extracted_json")
        if not isinstance(extracted, dict):
            continue
        same_vendor = (extracted.get("vendor") or "").strip().casefold() == vendor.strip().casefold()
        same_invoice = (extracted.get("invoice_num") or "").strip().casefold() == invoice_num.strip().casefold()
        if not (same_vendor and same_invoice):
            continue
        try:
            ts = datetime.fromisoformat(d["timestamp"])
        except (ValueError, TypeError):
            ts = None
        if ts is None or ts >= cutoff:
            return d
    return None


def get_run(run_id: int) -> Optional[dict]:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_all_runs() -> list[dict]:
    """All runs ordered by timestamp desc. Used by the dashboard."""
    return list_runs()


def list_runs(decision: Optional[str] = None) -> list[dict]:
    conn = get_conn()
    try:
        if decision:
            rows = conn.execute(
                "SELECT * FROM runs WHERE decision = ? ORDER BY id DESC", (decision,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM runs ORDER BY id DESC").fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    for key in ("extracted_json", "validation_results_json", "stage_log_json"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    return d

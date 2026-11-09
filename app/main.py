"""FastAPI app: upload form, live run view, and dashboard."""
import os
import shutil
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import db
from app.ingest import ingest_pdf
from app.extract import extract_fields
from app.match import match_invoice_to_po, load_po_dataset
from app.validate import validate_against_po
from app.decide import decide

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Zamp Invoice Processing")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
_po_dataset = None


def get_po_dataset():
    global _po_dataset
    if _po_dataset is None:
        _po_dataset = load_po_dataset()
    return _po_dataset


SAMPLE_DIR = Path(__file__).resolve().parent.parent / "data" / "test_invoices"

SAMPLES = [
    {"file": "01_happy_path_acme.pdf",           "label": "Happy path — Approve"},
    {"file": "03_ec1_scanned_invoice.pdf",        "label": "EC1: Scanned PDF (OCR)"},
    {"file": "04_ec2_split_po_invoice1.pdf",      "label": "EC2: Split PO part 1"},
    {"file": "05_ec2_split_po_invoice2.pdf",      "label": "EC2: Split PO part 2"},
    {"file": "06_ec3_within_tolerance.pdf",       "label": "EC3a: Within tolerance — Approve"},
    {"file": "07_ec3_outside_tolerance.pdf",      "label": "EC3b: Outside tolerance — Hold"},
    {"file": "08_ec4_missing_invoice_number.pdf", "label": "EC4a: Missing invoice number"},
    {"file": "09_ec4_unapproved_vendor.pdf",      "label": "EC4b: Unapproved vendor — Reject"},
    {"file": "10_ec4_duplicate.pdf",              "label": "EC4c: Duplicate invoice — Reject"},
]


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    # Reload PO dataset cache on startup so a fresh container picks it up
    get_po_dataset()


@app.get("/", response_class=HTMLResponse)
def upload_form(request: Request):
    samples = [s for s in SAMPLES if (SAMPLE_DIR / s["file"]).exists()]
    return templates.TemplateResponse("upload.html", {"request": request, "samples": samples})


@app.post("/run-sample/{filename}")
async def run_sample(filename: str):
    """Process one of the bundled sample invoices directly — no file upload needed."""
    safe = Path(filename).name  # strip any path traversal
    filepath = SAMPLE_DIR / safe
    if not filepath.exists() or filepath.suffix.lower() != ".pdf":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Sample not found")

    stage_log = []
    ingest = ingest_pdf(filepath)
    stage_log.append({"stage": "ingest", "result": {k: v for k, v in ingest.items() if k != "text"}})
    extracted = extract_fields(ingest["text"], pdf_path=filepath, gemini_key=GEMINI_KEY,
                               source_confidence=ingest["confidence"] if ingest["confidence"] > 0 else 1.0)
    stage_log.append({"stage": "extract", "result": extracted})
    po_dataset = get_po_dataset()
    match = match_invoice_to_po(extracted, po_dataset)
    stage_log.append({"stage": "match", "result": {k: v for k, v in match.items() if k != "candidates"}})
    validation = validate_against_po(extracted, match["matched_po"])
    stage_log.append({"stage": "validate", "result": validation})
    decision_result = decide(validation, match["matched_po"], extracted["extraction_confidence"])
    stage_log.append({"stage": "decide", "result": decision_result})
    run_id = db.save_run(filename=safe, extracted=extracted, matched_po=match["matched_po"],
                         validation=validation, decision=decision_result["decision"],
                         reasoning=decision_result["reasoning"], confidence=decision_result["confidence"],
                         stage_log=stage_log)
    return RedirectResponse(url=f"/run/{run_id}", status_code=303)


@app.post("/upload")
async def upload_invoice(file: UploadFile = File(...)):
    suffix = Path(file.filename).suffix or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        stage_log = []
        ingest = ingest_pdf(tmp_path)
        stage_log.append({"stage": "ingest", "result": {k: v for k, v in ingest.items() if k != "text"}})

        extracted = extract_fields(
            ingest["text"],
            pdf_path=tmp_path,
            gemini_key=GEMINI_KEY,
            source_confidence=ingest["confidence"] if ingest["confidence"] > 0 else 1.0,
        )
        stage_log.append({"stage": "extract", "result": extracted})

        po_dataset = get_po_dataset()
        match = match_invoice_to_po(extracted, po_dataset)
        stage_log.append({"stage": "match", "result": {k: v for k, v in match.items() if k != "candidates"}})

        validation = validate_against_po(extracted, match["matched_po"])
        stage_log.append({"stage": "validate", "result": validation})

        decision_result = decide(validation, match["matched_po"], extracted["extraction_confidence"])
        stage_log.append({"stage": "decide", "result": decision_result})

        run_id = db.save_run(
            filename=file.filename,
            extracted=extracted,
            matched_po=match["matched_po"],
            validation=validation,
            decision=decision_result["decision"],
            reasoning=decision_result["reasoning"],
            confidence=decision_result["confidence"],
            stage_log=stage_log,
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    return RedirectResponse(url=f"/run/{run_id}", status_code=303)


@app.get("/run/{run_id}", response_class=HTMLResponse)
def view_run(request: Request, run_id: int):
    run = db.get_run(run_id)
    if run is None:
        return HTMLResponse("<h2>Run not found</h2><a href='/dashboard'>Back</a>", status_code=404)
    return templates.TemplateResponse("run.html", {"request": request, "run": run, "run_id": run_id})


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    runs = db.get_all_runs()
    return templates.TemplateResponse("dashboard.html", {"request": request, "runs": runs})


@app.post("/reset-demo")
def reset_demo():
    """Wipe all run history — demo reset only. Requires a deliberate POST."""
    db.reset_runs()
    return RedirectResponse(url="/dashboard", status_code=303)


@app.get("/stats")
def stats():
    runs = db.get_all_runs()
    approved = sum(1 for r in runs if r.get("decision") == "Approve")
    hold = sum(1 for r in runs if r.get("decision") == "Hold for Review")
    rejected = sum(1 for r in runs if r.get("decision") == "Reject")
    return {"total": len(runs), "approved": approved, "hold": hold, "rejected": rejected}


@app.get("/health")
def health():
    key = os.getenv("GEMINI_API_KEY")
    return {"status": "ok", "gemini_key_loaded": bool(key) and key != "your_actual_key_here"}

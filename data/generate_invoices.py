"""Reproducible generator for test invoice PDFs (happy path + edge cases).

Run: python data/generate_invoices.py
Produces PDFs into data/test_invoices/, plus a manifest.json describing
what each file is meant to exercise (used by README / demo script, not
by the pipeline itself).
"""
import json
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from PIL import Image, ImageFilter
import io

try:
    import pymupdf as fitz
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False

BASE_DIR = Path(__file__).resolve().parent
OUT_DIR = BASE_DIR / "test_invoices"
OUT_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST = []


def draw_invoice(
    filename: str,
    vendor: str,
    invoice_no: str | None,
    date: str,
    po_ref: str | None,
    line_items: list[dict],
    subtotal: float,
    tax: float,
    total: float,
    itemised: bool = True,
    tax_embedded: bool = False,
    note: str | None = None,
    implied_po_text: str | None = None,
):
    path = OUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    y = height - 25 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, vendor)
    y -= 10 * mm

    c.setFont("Helvetica", 10)
    c.drawString(20 * mm, y, "INVOICE")
    y -= 7 * mm

    if invoice_no:
        c.drawString(20 * mm, y, f"Invoice #: {invoice_no}")
        y -= 6 * mm
    c.drawString(20 * mm, y, f"Date: {date}")
    y -= 6 * mm

    if po_ref:
        c.drawString(20 * mm, y, f"PO Reference: {po_ref}")
        y -= 6 * mm
    elif implied_po_text:
        c.drawString(20 * mm, y, implied_po_text)
        y -= 6 * mm

    y -= 6 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Description")
    c.drawString(120 * mm, y, "Qty")
    c.drawString(140 * mm, y, "Unit Price")
    c.drawString(170 * mm, y, "Amount")
    y -= 5 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    c.setFont("Helvetica", 9)
    if itemised:
        for item in line_items:
            desc = item["description"]
            qty = item["qty"]
            unit_price = item["unit_price"]
            amount = qty * unit_price
            c.drawString(20 * mm, y, desc[:48])
            c.drawString(120 * mm, y, str(qty))
            c.drawString(140 * mm, y, f"{unit_price:,.2f}")
            c.drawString(170 * mm, y, f"{amount:,.2f}")
            y -= 6 * mm
    else:
        bundled_desc = " + ".join(i["description"] for i in line_items)
        c.drawString(20 * mm, y, bundled_desc[:60])
        c.drawString(170 * mm, y, f"{subtotal:,.2f}")
        y -= 6 * mm

    y -= 4 * mm
    c.line(120 * mm, y, 190 * mm, y)
    y -= 7 * mm

    c.setFont("Helvetica", 10)
    if tax_embedded:
        c.drawString(140 * mm, y, "Total (tax incl.):")
        c.drawString(170 * mm, y, f"{total:,.2f}")
        y -= 6 * mm
    else:
        c.drawString(140 * mm, y, "Subtotal:")
        c.drawString(170 * mm, y, f"{subtotal:,.2f}")
        y -= 6 * mm
        c.drawString(140 * mm, y, "Tax:")
        c.drawString(170 * mm, y, f"{tax:,.2f}")
        y -= 6 * mm
        c.setFont("Helvetica-Bold", 10)
        c.drawString(140 * mm, y, "Total:")
        c.drawString(170 * mm, y, f"{total:,.2f}")
        y -= 6 * mm

    if note:
        y -= 10 * mm
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(20 * mm, y, note)

    c.showPage()
    c.save()
    return path


def flatten_to_scanned_image(pdf_path: Path, out_path: Path):
    """Render a clean PDF to a noisy flattened image-only PDF (no text layer),
    simulating a scanned document for OCR fallback testing."""
    if not HAS_FITZ:
        print(f"  [skip] PyMuPDF not available, cannot flatten {pdf_path.name}")
        return None
    doc = fitz.open(str(pdf_path))
    page = doc[0]
    pix = page.get_pixmap(dpi=150)
    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
    doc.close()
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    img = img.point(lambda p: p * 0.92 + 8)

    c = canvas.Canvas(str(out_path), pagesize=A4)
    width, height = A4
    img_buf = io.BytesIO()
    img.save(img_buf, format="JPEG", quality=55)
    img_buf.seek(0)
    from reportlab.lib.utils import ImageReader
    c.drawImage(ImageReader(img_buf), 0, 0, width=width, height=height)
    c.showPage()
    c.save()
    return out_path


def add_manifest(filename: str, scenario: str, expected: str):
    MANIFEST.append({"filename": filename, "scenario": scenario, "expected": expected})


def main():
    # 1. Happy path — clean, itemised, explicit PO, exact match
    draw_invoice(
        "01_happy_path_acme.pdf",
        vendor="Acme Office Supplies",
        invoice_no="INV-2024-001",
        date="2026-09-20",
        po_ref="PO-1001",
        line_items=[
            {"description": "A4 Paper Ream (Box of 10)", "qty": 20, "unit_price": 950.00},
            {"description": "Ballpoint Pens (Box of 50)", "qty": 10, "unit_price": 1120.00},
        ],
        subtotal=30200.00,
        tax=18000.00,
        total=48200.00,
        itemised=True,
    )
    add_manifest("01_happy_path_acme.pdf", "Happy path: clean PDF, explicit PO, exact amount match", "Approve")

    # 2. Bundled line items, tax embedded, explicit PO
    draw_invoice(
        "02_bundled_bluewave.pdf",
        vendor="Bluewave IT Services",
        invoice_no="BW-5521",
        date="2026-09-25",
        po_ref="PO-1002",
        line_items=[{"description": "Laptop Maintenance Contract - Q4", "qty": 1, "unit_price": 125000.00}],
        subtotal=125000.00,
        tax=0,
        total=125000.00,
        itemised=False,
        tax_embedded=True,
    )
    add_manifest("02_bundled_bluewave.pdf", "Bundled line items, tax embedded, exact match", "Approve")

    # 3. Implied PO reference (no explicit PO number), still matchable by vendor + amount
    draw_invoice(
        "03_implied_po_horizon.pdf",
        vendor="Horizon Facilities Mgmt",
        invoice_no="HFM-991",
        date="2026-09-21",
        po_ref=None,
        implied_po_text="Re: Monthly Housekeeping Services agreement dated 2026-08-20",
        line_items=[{"description": "Monthly Housekeeping Services", "qty": 1, "unit_price": 36000.00}],
        subtotal=36000.00,
        tax=0,
        total=36000.00,
        itemised=True,
        tax_embedded=True,
    )
    add_manifest("03_implied_po_horizon.pdf", "No explicit PO number; must match via vendor+amount", "Approve or Hold (ambiguous match)")

    # EC3a — within tolerance (1.5% over PO-1004, tolerance 2%)
    po4_amount = 90000.00
    over_1_5 = round(po4_amount * 1.015, 2)
    draw_invoice(
        "04_ec3_within_tolerance_crestline.pdf",
        vendor="Crestline Packaging Co",
        invoice_no="CP-3301",
        date="2026-09-14",
        po_ref="PO-1004",
        line_items=[{"description": "Corrugated Boxes (Pallet)", "qty": 3, "unit_price": round(over_1_5 / 3, 2)}],
        subtotal=over_1_5,
        tax=0,
        total=over_1_5,
        itemised=True,
        tax_embedded=True,
        note="EC3: total is 1.5% over PO amount (within 2% tolerance).",
    )
    add_manifest("04_ec3_within_tolerance_crestline.pdf", "EC3a: invoice 1.5% over PO amount (within 2% tolerance)", "Approve with note")

    # EC3b — outside tolerance (8% over PO-1005)
    po5_amount = 215000.00
    over_8 = round(po5_amount * 1.08, 2)
    draw_invoice(
        "05_ec3_outside_tolerance_stratos.pdf",
        vendor="Stratos Cloud Hosting",
        invoice_no="SCH-7788",
        date="2026-07-10",
        po_ref="PO-1005",
        line_items=[{"description": "Cloud Hosting - Annual Plan", "qty": 1, "unit_price": over_8}],
        subtotal=over_8,
        tax=0,
        total=over_8,
        itemised=True,
        tax_embedded=True,
        note="EC3: total is 8% over PO amount (outside 2% tolerance).",
    )
    add_manifest("05_ec3_outside_tolerance_stratos.pdf", "EC3b: invoice 8% over PO amount (outside tolerance)", "Hold for Review")

    # EC4b — vendor not on approved list (PO-1016 approved=false)
    draw_invoice(
        "06_ec4b_unapproved_vendor_summit.pdf",
        vendor="Summit Legal Advisors",
        invoice_no="SLA-440",
        date="2026-07-15",
        po_ref="PO-1016",
        line_items=[{"description": "Contract Review Retainer", "qty": 1, "unit_price": 120000.00}],
        subtotal=120000.00,
        tax=0,
        total=120000.00,
        itemised=True,
        tax_embedded=True,
        note="EC4b: vendor is not on the approved vendor list.",
    )
    add_manifest("06_ec4b_unapproved_vendor_summit.pdf", "EC4b: vendor not on approved list", "Reject")

    # EC4a — missing invoice number
    draw_invoice(
        "07_ec4a_missing_invoice_number_meridian.pdf",
        vendor="Meridian Catering Services",
        invoice_no=None,
        date="2026-09-23",
        po_ref="PO-1006",
        line_items=[{"description": "Corporate Event Catering", "qty": 1, "unit_price": 54000.00}],
        subtotal=54000.00,
        tax=0,
        total=54000.00,
        itemised=True,
        tax_embedded=True,
        note="EC4a: invoice number intentionally omitted.",
    )
    add_manifest("07_ec4a_missing_invoice_number_meridian.pdf", "EC4a: missing invoice number", "Hold for Review")

    # EC4c — duplicate submission (two identical invoices, same vendor+invoice#)
    draw_invoice(
        "08_ec4c_duplicate_falcon_A.pdf",
        vendor="Falcon Logistics Pvt Ltd",
        invoice_no="FL-6002",
        date="2026-09-06",
        po_ref="PO-1007",
        line_items=[{"description": "Freight - Mumbai to Delhi (Monthly)", "qty": 1, "unit_price": 72000.00}],
        subtotal=72000.00,
        tax=0,
        total=72000.00,
        itemised=True,
        tax_embedded=True,
    )
    add_manifest("08_ec4c_duplicate_falcon_A.pdf", "EC4c: first submission of this invoice (baseline)", "Approve")

    draw_invoice(
        "09_ec4c_duplicate_falcon_B.pdf",
        vendor="Falcon Logistics Pvt Ltd",
        invoice_no="FL-6002",
        date="2026-09-06",
        po_ref="PO-1007",
        line_items=[{"description": "Freight - Mumbai to Delhi (Monthly)", "qty": 1, "unit_price": 72000.00}],
        subtotal=72000.00,
        tax=0,
        total=72000.00,
        itemised=True,
        tax_embedded=True,
        note="EC4c: duplicate re-submission of FL-6002, submit after 08_... in demo.",
    )
    add_manifest("09_ec4c_duplicate_falcon_B.pdf", "EC4c: duplicate re-submission (same vendor+invoice#) — submit AFTER file 08", "Hold for Review (duplicate)")

    # EC2 — split PO across multiple invoices (PO-1008, total 310000)
    po8_total = 310000.00
    split_a = round(po8_total * 0.5, 2)
    split_b = round(po8_total * 0.5, 2)
    draw_invoice(
        "10_ec2_split_po_pinecrest_part1.pdf",
        vendor="Pinecrest Office Interiors",
        invoice_no="PI-801",
        date="2026-07-01",
        po_ref="PO-1008",
        line_items=[{"description": "Office Workstations (Set of 10) - Partial Shipment 1", "qty": 1, "unit_price": split_a}],
        subtotal=split_a,
        tax=0,
        total=split_a,
        itemised=True,
        tax_embedded=True,
        note="EC2: partial invoice 1 of 2 against PO-1008.",
    )
    add_manifest("10_ec2_split_po_pinecrest_part1.pdf", "EC2: partial invoice 1/2 against a single PO (50% of PO amount)", "Approve (partial, within PO total)")

    draw_invoice(
        "11_ec2_split_po_pinecrest_part2.pdf",
        vendor="Pinecrest Office Interiors",
        invoice_no="PI-802",
        date="2026-07-15",
        po_ref="PO-1008",
        line_items=[{"description": "Office Workstations (Set of 10) - Partial Shipment 2", "qty": 1, "unit_price": split_b}],
        subtotal=split_b,
        tax=0,
        total=split_b,
        itemised=True,
        tax_embedded=True,
        note="EC2: partial invoice 2 of 2 against PO-1008; cumulative = PO amount. Submit after part1.",
    )
    add_manifest("11_ec2_split_po_pinecrest_part2.pdf", "EC2: partial invoice 2/2 — cumulative matches PO total — submit AFTER file 10", "Approve (cumulative == PO amount)")

    # EC1 — scanned invoice (no text layer). Build clean source then flatten to image-only PDF.
    clean_source = draw_invoice(
        "12_ec1_scanned_source_nimbus.pdf",
        vendor="Nimbus Marketing Agency",
        invoice_no="NM-204",
        date="2026-07-20",
        po_ref="PO-1009",
        line_items=[{"description": "Q3 Digital Marketing Campaign", "qty": 1, "unit_price": 180000.00}],
        subtotal=180000.00,
        tax=0,
        total=180000.00,
        itemised=True,
        tax_embedded=True,
    )
    scanned_out = OUT_DIR / "12_ec1_scanned_nimbus.pdf"
    result = flatten_to_scanned_image(clean_source, scanned_out)
    if result:
        clean_source.unlink()
        add_manifest("12_ec1_scanned_nimbus.pdf", "EC1: scanned/flattened PDF, no text layer -> OCR fallback, lower confidence", "Approve with low-confidence OCR flag (or Hold if OCR garbles fields)")
    else:
        clean_source.rename(scanned_out)
        add_manifest("12_ec1_scanned_nimbus.pdf", "EC1: intended scanned PDF (poppler unavailable, left as text PDF — regenerate with poppler installed for true OCR test)", "N/A - needs poppler for true scan simulation")

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(MANIFEST, indent=2), encoding="utf-8")
    print(f"Generated {len(MANIFEST)} invoice PDFs into {OUT_DIR}")
    print(f"Manifest written to {manifest_path}")


if __name__ == "__main__":
    main()

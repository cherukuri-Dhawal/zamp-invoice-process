"""Generate the new test invoices needed for run_all_invoices.py.

Produces:
  03_ec1_scanned_invoice.pdf   - image-only, no text layer (TechSupplies Ltd)
  04_ec2_split_po_invoice1.pdf - split PO part 1 (Global Parts Co, Rs.30,000)
  05_ec2_split_po_invoice2.pdf - split PO part 2 (Global Parts Co, Rs.32,000)
  06_ec3_within_tolerance.pdf  - Metro Supplies, Rs.51,000 (2% over Rs.50,000 PO)
  07_ec3_outside_tolerance.pdf - Metro Supplies, Rs.54,000 (8% over Rs.50,000 PO)
  08_ec4_missing_invoice_number.pdf - ACME Corp, no invoice number, Rs.48,200
  09_ec4_unapproved_vendor.pdf - ShadySuppliers Inc (unapproved), Rs.15,000
  10_ec4_duplicate.pdf         - ACME Corp INV-2024-001 Rs.48,200 (duplicate of invoice 1)
"""
import io
import sys
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas
except ImportError:
    print("reportlab not installed. Run: pip install reportlab")
    sys.exit(1)

OUT_DIR = Path(__file__).resolve().parent / "test_invoices"
OUT_DIR.mkdir(exist_ok=True)


def _make_invoice(
    filename: str,
    vendor: str,
    invoice_no: str | None,
    date: str,
    po_ref: str,
    line_items: list[tuple[str, int, float]],
    subtotal: float,
    tax: float,
    total: float,
) -> Path:
    out = OUT_DIR / filename
    c = canvas.Canvas(str(out), pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 20 * mm, vendor)

    c.setFont("Helvetica", 10)
    y = h - 32 * mm
    if invoice_no is not None:
        c.drawString(20 * mm, y, f"Invoice #: {invoice_no}")
        y -= 7 * mm
    c.drawString(20 * mm, y, f"Date: {date}")
    y -= 7 * mm
    c.drawString(20 * mm, y, f"PO Reference: {po_ref}")
    y -= 12 * mm

    # Table header
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, "Description")
    c.drawString(110 * mm, y, "Qty")
    c.drawString(130 * mm, y, "Unit Price")
    c.drawString(160 * mm, y, "Amount")
    y -= 6 * mm
    c.line(20 * mm, y, 190 * mm, y)
    y -= 6 * mm

    c.setFont("Helvetica", 10)
    for desc, qty, unit in line_items:
        amt = qty * unit
        c.drawString(20 * mm, y, desc)
        c.drawString(110 * mm, y, str(qty))
        c.drawString(130 * mm, y, f"{unit:,.2f}")
        c.drawString(160 * mm, y, f"{amt:,.2f}")
        y -= 7 * mm

    y -= 4 * mm
    c.drawString(130 * mm, y, f"Subtotal: {subtotal:,.2f}")
    y -= 7 * mm
    c.drawString(130 * mm, y, f"Tax: {tax:,.2f}")
    y -= 7 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(130 * mm, y, f"Total: {total:,.2f}")

    c.save()
    return out


def _flatten_to_image(src: Path, dst: Path) -> None:
    """Rasterize PDF to image-only PDF (no text layer) using PyMuPDF."""
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # type: ignore

    src_doc = fitz.open(str(src))
    out_doc = fitz.open()
    for page in src_doc:
        pix = page.get_pixmap(dpi=150)
        img_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
        img_page.insert_image(img_page.rect, pixmap=pix)
    out_doc.save(str(dst))
    src_doc.close()
    out_doc.close()


def main():
    # --- 03: EC1 scanned (TechSupplies Ltd, Rs.25,000, PO-1019) ---
    tmp = OUT_DIR / "_tmp_03.pdf"
    _make_invoice(
        "_tmp_03.pdf", "TechSupplies Ltd", "TS-5501", "2026-10-05", "PO-1019",
        [("IT Consumables - Quarterly", 1, 25000.00)],
        25000.00, 0.00, 25000.00,
    )
    _flatten_to_image(tmp, OUT_DIR / "03_ec1_scanned_invoice.pdf")
    tmp.unlink(missing_ok=True)
    print("Generated 03_ec1_scanned_invoice.pdf (image-only, no text layer)")

    # --- 04: EC2 split PO part 1 (Global Parts Co, Rs.30,000, PO-1020) ---
    _make_invoice(
        "04_ec2_split_po_invoice1.pdf", "Global Parts Co", "GP-1001", "2026-10-08", "PO-1020",
        [("Machine Parts - Batch A", 1, 30000.00)],
        30000.00, 0.00, 30000.00,
    )
    print("Generated 04_ec2_split_po_invoice1.pdf")

    # --- 05: EC2 split PO part 2 (Global Parts Co, Rs.32,000, PO-1020) ---
    _make_invoice(
        "05_ec2_split_po_invoice2.pdf", "Global Parts Co", "GP-1002", "2026-10-15", "PO-1020",
        [("Machine Parts - Batch B", 1, 32000.00)],
        32000.00, 0.00, 32000.00,
    )
    print("Generated 05_ec2_split_po_invoice2.pdf")

    # --- 06: EC3 within tolerance (Metro Supplies, Rs.51,000 = 2% over Rs.50,000, PO-1021) ---
    _make_invoice(
        "06_ec3_within_tolerance.pdf", "Metro Supplies", "MS-3001", "2026-10-10", "PO-1021",
        [("Office Supplies - Monthly", 1, 51000.00)],
        51000.00, 0.00, 51000.00,
    )
    print("Generated 06_ec3_within_tolerance.pdf")

    # --- 07: EC3 outside tolerance (Metro Supplies, Rs.54,000 = 8% over Rs.50,000, PO-1021) ---
    _make_invoice(
        "07_ec3_outside_tolerance.pdf", "Metro Supplies", "MS-3002", "2026-10-12", "PO-1021",
        [("Office Supplies - Monthly (Extra)", 1, 54000.00)],
        54000.00, 0.00, 54000.00,
    )
    print("Generated 07_ec3_outside_tolerance.pdf")

    # --- 08: EC4 missing invoice number (ACME Corp, Rs.48,200, PO-1001) ---
    _make_invoice(
        "08_ec4_missing_invoice_number.pdf", "Acme Office Supplies", None, "2026-10-15", "PO-1001",
        [("A4 Paper Ream (Box of 10)", 20, 950.00), ("Ballpoint Pens (Box of 50)", 10, 1120.00)],
        30200.00, 18000.00, 48200.00,
    )
    print("Generated 08_ec4_missing_invoice_number.pdf")

    # --- 09: EC4 unapproved vendor (ShadySuppliers Inc, Rs.15,000, PO-1022) ---
    _make_invoice(
        "09_ec4_unapproved_vendor.pdf", "ShadySuppliers Inc", "SS-9999", "2026-10-16", "PO-1022",
        [("Miscellaneous Supplies", 1, 15000.00)],
        15000.00, 0.00, 15000.00,
    )
    print("Generated 09_ec4_unapproved_vendor.pdf")

    # --- 10: EC4 duplicate (same as invoice 01: Acme Office Supplies, INV-2024-001, Rs.48,200) ---
    _make_invoice(
        "10_ec4_duplicate.pdf", "Acme Office Supplies", "INV-2024-001", "2026-10-20", "PO-1001",
        [("A4 Paper Ream (Box of 10)", 20, 950.00), ("Ballpoint Pens (Box of 50)", 10, 1120.00)],
        30200.00, 18000.00, 48200.00,
    )
    print("Generated 10_ec4_duplicate.pdf")

    print("\nAll 8 new invoice files generated.")


if __name__ == "__main__":
    main()

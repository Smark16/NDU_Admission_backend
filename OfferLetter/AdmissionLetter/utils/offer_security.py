"""
Stamp admission offer-letter PDFs with:
- QR code linking to the public verify URL (optional if `qrcode` is installed)
- Footer text: Printed by, system name (lowercase), date/time, verify URL
"""
from __future__ import annotations

import logging
from io import BytesIO

logger = logging.getLogger(__name__)


def stamp_offer_letter_pdf(
    pdf_bytes: bytes,
    *,
    verify_url: str,
    printed_by: str,
    system_name: str,
    generated_at: str,
) -> bytes:
    """Append security footer + QR on the last page of the PDF."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[-1]
    rect = page.rect

    margin = 32
    qr_size = 58
    text_right = rect.width - margin - qr_size - 8
    y0 = rect.height - 76

    footer_lines = [
        f"Printed by: {printed_by}",
        f"{system_name.lower()}  ·  {generated_at}",
        f"Verify: {verify_url}",
    ]
    y = y0
    for line in footer_lines:
        page.insert_text(
            fitz.Point(margin, y),
            line[:500],
            fontsize=6.5,
            color=(0.32, 0.32, 0.32),
            fontname="helv",
        )
        y += 9

    try:
        import qrcode

        qr = qrcode.QRCode(version=None, box_size=2, border=1)
        qr.add_data(verify_url)
        qr.make(fit=True)
        pil_img = qr.make_image(fill_color="black", back_color="white")
        buf = BytesIO()
        pil_img.save(buf, format="PNG")
        buf.seek(0)
        qr_rect = fitz.Rect(
            rect.width - margin - qr_size,
            rect.height - margin - qr_size,
            rect.width - margin,
            rect.height - margin,
        )
        page.insert_image(qr_rect, stream=buf.getvalue())
    except Exception as e:
        logger.info("QR stamp skipped (install qrcode+pillow for QR): %s", e)

    out = doc.write()
    doc.close()
    return out

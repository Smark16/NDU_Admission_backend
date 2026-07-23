"""Render Bursar weekly report PDF (xhtml2pdf)."""
from __future__ import annotations

import io
from typing import Any

from django.template.loader import render_to_string
from django.utils import timezone

from accounts.portal_branding import xhtml2pdf_link_callback


def render_bursar_weekly_pdf(metrics: dict[str, Any]) -> tuple[bytes, str]:
    """Return (pdf_bytes, filename)."""
    html = render_to_string("payments/bursar_weekly_report.html", {"m": metrics})
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise RuntimeError("xhtml2pdf is required to render the bursar report PDF.") from exc

    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf, link_callback=xhtml2pdf_link_callback)
    if result.err:
        raise RuntimeError("Failed to render bursar weekly report PDF.")

    date_stamp = timezone.localdate().isoformat()
    filename = f"Bursar_Weekly_Report_{date_stamp}.pdf"
    return buf.getvalue(), filename

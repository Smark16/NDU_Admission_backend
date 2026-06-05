"""Examination card PDF for students with full outstanding balance cleared."""
from __future__ import annotations

import base64
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from admissions.models import AdmittedStudent

from .exam_card import build_exam_card_payload, issue_or_refresh_exam_card_token, qr_png_base64
from .provisional_results_pdf import _load_logo_b64


def render_exam_card_pdf(student: AdmittedStudent, *, request=None) -> bytes:
    token = issue_or_refresh_exam_card_token(student)
    if not token:
        raise ValueError("Student is not eligible for an examination card.")

    payload = build_exam_card_payload(student, request=request, issue_token=False)
    if not payload["can_print"]:
        raise ValueError("Student is not eligible for an examination card.")

    verify_url = payload["verify_url"]
    qr_b64 = payload["qr_png_base64"] or qr_png_base64(verify_url)

    photo_b64 = None
    app = getattr(student, "application", None)
    if app and app.passport_photo:
        try:
            with app.passport_photo.open("rb") as fh:
                photo_b64 = base64.b64encode(fh.read()).decode("ascii")
        except Exception:
            photo_b64 = None

    context = {
        "student_name": (student.full_name or "").upper(),
        "reg_no": student.reg_no or "",
        "program": (student.admitted_program.name if student.admitted_program else "").upper(),
        "exam_period_label": payload["exam_period_label"],
        "finance_cleared": payload["finance"]["tuition_cleared"],
        "finance_message": payload["finance"]["message"],
        "courses": payload["courses"],
        "verify_url": verify_url,
        "qr_b64": qr_b64,
        "photo_b64": photo_b64,
        "logo_b64": _load_logo_b64(),
        "issued_at": timezone.localtime(token.issued_at).strftime("%d %B %Y %I:%M %p"),
        "verification_code": str(token.verification_code),
    }

    html = render_to_string("examinations/exam_card.html", context)
    from xhtml2pdf import pisa
    import io

    pdf_buffer = io.BytesIO()
    base_url = str(Path(settings.BASE_DIR).as_uri()) + "/"
    result = pisa.CreatePDF(html, dest=pdf_buffer, link_callback=lambda *args: base_url)
    if result.err:
        raise RuntimeError("Examination card PDF generation failed.")
    pdf_buffer.seek(0)
    return pdf_buffer.read()

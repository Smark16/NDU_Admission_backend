"""PDF export for test/exam registration sheets."""
from __future__ import annotations

import io

from django.template.loader import render_to_string
from django.utils import timezone

from accounts.portal_branding import load_portal_logo_b64_for_pdf, xhtml2pdf_link_callback


def _portal_branding() -> dict:
    try:
        from accounts.models import SystemSettings

        settings_obj = SystemSettings.get_settings()
        university_name = (settings_obj.university_name or "NDEJJE UNIVERSITY").strip()
    except Exception:
        university_name = "NDEJJE UNIVERSITY"
    return {
        "university_name": university_name,
        "logo_b64": load_portal_logo_b64_for_pdf(),
    }


def build_test_exam_registration_context(
    *,
    kind: str,
    course_code: str,
    course_name: str,
    programme_name: str,
    semester_name: str,
    min_pct: float,
    students: list[dict],
) -> dict:
    branding = _portal_branding()
    kind_label = "Test" if kind == "test" else "Exam"
    return {
        **branding,
        "title": f"{kind_label} Registration Sheet",
        "kind_label": kind_label,
        "min_pct": min_pct,
        "course_code": course_code,
        "course_name": course_name,
        "programme_name": programme_name,
        "semester_name": semester_name,
        "students": students,
        "student_count": len(students),
        "generated_at": timezone.localtime().strftime("%d %B %Y %I:%M %p"),
        "disclaimer": (
            f"Lists students enrolled on this course unit who meet the {min_pct:.0f}% tuition "
            f"payment requirement to sit this {kind_label.lower()}, or hold an active "
            "temporary access pass."
        ),
    }


def render_test_exam_registration_pdf(context: dict) -> bytes:
    html = render_to_string("programs/test_exam_registration_sheet_pdf.html", context)
    from xhtml2pdf import pisa

    pdf_buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=pdf_buffer, link_callback=xhtml2pdf_link_callback)
    if result.err:
        raise RuntimeError("Test/exam registration sheet PDF generation failed.")
    pdf_buffer.seek(0)
    return pdf_buffer.read()


def safe_test_exam_pdf_filename(kind: str, course_code: str) -> str:
    code = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (course_code or "course"))
    date_part = timezone.localdate().strftime("%Y%m%d")
    return f"{kind.capitalize()}Registration_{code.strip('_') or 'course'}_{date_part}.pdf"

"""PDF export for lecture attendance sheets."""
from __future__ import annotations

import io
from pathlib import Path

from django.conf import settings
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


def build_attendance_sheet_context(
    *,
    course_code: str,
    course_name: str,
    session_date_label: str,
    programme_name: str,
    semester_name: str,
    venue_label: str,
    taken_by_name: str,
    students: list[dict],
    blank_sheet: bool = False,
) -> dict:
    branding = _portal_branding()
    present = sum(1 for s in students if s.get("status") == "present")
    late = sum(1 for s in students if s.get("status") == "late")
    excused = sum(1 for s in students if s.get("status") == "excused")
    absent = sum(1 for s in students if s.get("status") == "absent")
    return {
        **branding,
        "title": "Lecture Attendance Sheet",
        "course_code": course_code,
        "course_name": course_name,
        "session_date_label": session_date_label,
        "programme_name": programme_name,
        "semester_name": semester_name,
        "venue_label": venue_label or "—",
        "taken_by_name": taken_by_name or "—",
        "students": students,
        "blank_sheet": blank_sheet,
        "student_count": len(students),
        "present_count": present,
        "late_count": late,
        "excused_count": excused,
        "absent_count": absent,
        "generated_at": timezone.localtime().strftime("%d %B %Y %I:%M %p"),
        "disclaimer": (
            "Blank sheets are for class signing. Marked sheets reflect saved portal attendance."
        ),
    }


def render_attendance_sheet_pdf(context: dict) -> bytes:
    html = render_to_string("programs/attendance_sheet_pdf.html", context)
    from xhtml2pdf import pisa

    pdf_buffer = io.BytesIO()
    result = pisa.CreatePDF(html, dest=pdf_buffer, link_callback=xhtml2pdf_link_callback)
    if result.err:
        raise RuntimeError("Attendance sheet PDF generation failed.")
    pdf_buffer.seek(0)
    return pdf_buffer.read()


def safe_attendance_pdf_filename(course_code: str, session_date) -> str:
    code = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (course_code or "course"))
    date_part = session_date.strftime("%Y%m%d") if hasattr(session_date, "strftime") else str(session_date)
    return f"Attendance_{code.strip('_') or 'course'}_{date_part}.pdf"

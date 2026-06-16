"""PDF export for student and lecturer teaching timetables."""
from __future__ import annotations

import io
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.portal_branding import load_portal_logo_b64_for_pdf
from Programs.models import TimetableSession


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


def _semester_period_lines(sessions: list[dict]) -> list[str]:
    seen: dict[tuple[str, str, str], str] = {}
    for row in sessions:
        key = (
            row.get("semester_name") or "",
            row.get("semester_start") or "",
            row.get("semester_end") or "",
        )
        period = (row.get("semester_period") or "").strip()
        if period and key not in seen:
            seen[key] = period
    return list(seen.values())


def build_timetable_pdf_context(
    *,
    title: str,
    person_name: str,
    person_subtitle: str,
    sessions: list[dict],
    extra_lines: list[str] | None = None,
) -> dict:
    by_section: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in sessions:
        session_date = (row.get("session_date") or "").strip()
        if session_date:
            key = ("date", session_date)
        else:
            key = ("day", str(int(row.get("day_of_week") or 0)))
        by_section[key].append(row)

    day_sections = []
    for key in sorted(by_section.keys(), key=lambda item: item[1]):
        rows = sorted(by_section[key], key=lambda r: r.get("start_time") or "")
        if key[0] == "date":
            heading = rows[0].get("date_label") or key[1]
            subheading = rows[0].get("day_label") or ""
        else:
            day_num = int(key[1] or 0)
            heading = rows[0].get("day_label") or dict(TimetableSession.DAY_CHOICES).get(day_num, "")
            subheading = rows[0].get("date_label") or ""
        day_sections.append(
            {
                "day_label": heading,
                "date_label": subheading,
                "sessions": rows,
            }
        )

    branding = _portal_branding()
    semester_periods = _semester_period_lines(sessions)
    return {
        **branding,
        "title": title,
        "person_name": person_name,
        "person_subtitle": person_subtitle,
        "extra_lines": extra_lines or [],
        "semester_periods": semester_periods,
        "day_sections": day_sections,
        "session_count": len(sessions),
        "generated_at": timezone.localtime().strftime("%d %B %Y %I:%M %p"),
        "disclaimer": "This timetable shows published teaching sessions only. Confirm any changes with your faculty.",
    }


def render_timetable_pdf(context: dict) -> bytes:
    html = render_to_string("programs/my_timetable_pdf.html", context)
    from xhtml2pdf import pisa

    pdf_buffer = io.BytesIO()
    base_url = str(Path(settings.BASE_DIR).as_uri()) + "/"
    result = pisa.CreatePDF(html, dest=pdf_buffer, link_callback=lambda *args: base_url)
    if result.err:
        raise RuntimeError("Timetable PDF generation failed.")
    pdf_buffer.seek(0)
    return pdf_buffer.read()


def safe_pdf_filename(prefix: str, identifier: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (identifier or "timetable"))
    safe = safe.strip("_") or "timetable"
    return f"{prefix}_{safe}.pdf"

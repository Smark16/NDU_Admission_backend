from __future__ import annotations

import re
from datetime import date

from django.core.exceptions import ValidationError

# Canonical display format for all registry labels and batch fields.
ACADEMIC_YEAR_PATTERN = re.compile(r"^\d{4}/\d{4}$")


def get_current_academic_year() -> str:
    """Calendar rule (Aug+): label for the active university year."""
    today = date.today()
    year = today.year
    if today.month >= 8:
        start_year = year
        end_year = year + 1
    else:
        start_year = year - 1
        end_year = year
    return f"{start_year}/{end_year}"


def normalize_academic_year_label(raw: str) -> str:
    """
    Normalize user input to ``YYYY/YYYY``.
    Accepts ``2025-2026``, ``2025/26`` → ``2025/2026`` when unambiguous.
    """
    text = (raw or "").strip()
    if not text:
        return ""

    text = text.replace("-", "/").replace(" ", "")
    if ACADEMIC_YEAR_PATTERN.match(text):
        start = int(text[:4])
        end = int(text[5:9])
        if end == start + 1:
            return text
        raise ValidationError(
            f"Academic year end ({end}) must be exactly one year after start ({start})."
        )

    # e.g. 2025/26
    short = re.match(r"^(\d{4})/(\d{2})$", text)
    if short:
        start = int(short.group(1))
        end_suffix = int(short.group(2))
        end = (start // 100) * 100 + end_suffix
        if end < start:
            end += 100
        if end == start + 1:
            return f"{start}/{end}"
        raise ValidationError(
            f"Academic year must span one year (got {start}/{end})."
        )

    raise ValidationError(
        'Academic year must look like "2025/2026" (four-digit years separated by /).'
    )


def get_registered_academic_year_label(raw: str, *, strict: bool = True) -> str:
    """
    Return a normalized label that exists in ``AcademicYear`` when *strict*.
    When registry is empty, returns normalized label without DB check (bootstrap).
    """
    label = normalize_academic_year_label(raw)
    if not label:
        raise ValidationError("Academic year is required.")

    from admissions.models import AcademicYear

    if not AcademicYear.objects.exists():
        return label

    row = AcademicYear.objects.filter(label=label, is_active=True).first()
    if row:
        return row.label

    if strict:
        raise ValidationError(
            f'"{label}" is not in the academic year list. '
            "Add it under Admissions → Academic years first."
        )
    return label


def get_default_academic_year_label() -> str:
    """Prefer registry ``is_current``, else calendar rule."""
    from admissions.models import AcademicYear

    current = AcademicYear.objects.filter(is_current=True, is_active=True).first()
    if current:
        return current.label
    return get_current_academic_year()


def parse_academic_year_start(label: str) -> int:
    """Return the four-digit start year from a normalized label."""
    normalized = normalize_academic_year_label(label)
    return int(normalized[:4])


def format_academic_year_from_start(start_year: int) -> str:
    """Build canonical ``YYYY/YYYY`` from the intake start year."""
    if start_year < 1900 or start_year > 2100:
        raise ValidationError("Start year must be between 1900 and 2100.")
    return f"{start_year}/{start_year + 1}"


def suggest_next_academic_year_label() -> str:
    """
    Next label after the latest registry entry, else the calendar year.
    """
    from admissions.models import AcademicYear

    latest = AcademicYear.objects.order_by("-label").first()
    if latest:
        try:
            start = parse_academic_year_start(latest.label)
            return format_academic_year_from_start(start + 1)
        except ValidationError:
            pass
    return get_current_academic_year()


def suggest_academic_year_options(
    *,
    count: int = 6,
    past_count: int | None = None,
) -> list[str]:
    """
    Rolling list of labels for pickers: recent past years, the calendar year,
    and upcoming years — so staff can register previous years for historical batches.
    """
    start = parse_academic_year_start(get_current_academic_year())
    ahead = max(int(count), 1)
    behind = past_count if past_count is not None else ahead
    behind = max(int(behind), 0)
    return [
        format_academic_year_from_start(start + offset)
        for offset in range(-behind, ahead)
    ]
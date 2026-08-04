"""When scheduled fees become visible on the student portal."""
from __future__ import annotations

import calendar
from datetime import date, datetime

from django.utils import timezone


def parse_billing_date(value) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()[:10]
    if not text:
        return None
    return datetime.strptime(text, "%Y-%m-%d").date()


def _add_months(d: date, n: int) -> date:
    """Return d + n calendar months, clamped to the last day of that month."""
    month = d.month + n
    year = d.year + (month - 1) // 12
    month = ((month - 1) % 12) + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def terms_per_year_for_program(program) -> int:
    cal = getattr(program, "calendar_type", None) or "semester"
    return 3 if cal == "trimester" else 2


def months_per_term_for_program(program) -> int:
    cal = getattr(program, "calendar_type", None) or "semester"
    return 4 if cal == "trimester" else 6


def period_unit_for_calendar(calendar_type: str | None = None, program=None) -> str:
    """Human label for one academic period: Semester or Trimester (never 'Term')."""
    cal = calendar_type
    if not cal and program is not None:
        cal = getattr(program, "calendar_type", None)
    cal = (cal or "semester").strip().lower()
    return "Trimester" if cal == "trimester" else "Semester"


def curriculum_period_label(
    year_of_study: int | None,
    term_number: int | None,
    *,
    program=None,
    calendar_type: str | None = None,
    semester_name: str | None = None,
) -> str:
    """
    Display label for a curriculum position.

    Prefers the cohort semester name when present so tuition and scheduled fees
    (e.g. Room & Board) share one accordion group. Otherwise builds
    ``Year N Semester M`` / ``Year N Trimester M``.
    """
    name = (semester_name or "").strip()
    if name:
        return name
    try:
        y = int(year_of_study) if year_of_study is not None else None
        t = int(term_number) if term_number is not None else None
    except (TypeError, ValueError):
        y, t = None, None
    if y and t:
        unit = period_unit_for_calendar(calendar_type, program)
        return f"Year {y} {unit} {t}"
    return "Other fees"


def resolve_semester_for_year_term(
    *,
    program_batch_id: int | None,
    year_of_study: int,
    term_number: int,
):
    """Match an active cohort semester to a payable year/term (Room & Board, etc.)."""
    if not program_batch_id:
        return None
    from Programs.models import Semester

    return (
        Semester.objects.filter(
            program_batch_id=program_batch_id,
            year_of_study=year_of_study,
            term_number=term_number,
            is_active=True,
        )
        .order_by("order", "id")
        .first()
    )


def term_index_from_position(
    *,
    year_of_study: int | None,
    term_number: int | None,
    order: int | None,
    terms_per_year: int,
) -> int | None:
    """0-based index of this term from the cohort start (Year 1 Term 1 = 0)."""
    if year_of_study and term_number:
        y = int(year_of_study)
        t = int(term_number)
        if y >= 1 and t >= 1:
            return (y - 1) * terms_per_year + (t - 1)
    if order and int(order) >= 1:
        return int(order) - 1
    return None


def default_billing_date_for_semester(sem, program_batch, program) -> date | None:
    """
    First day a term's fees should appear on the student portal.

    Semester programmes use two terms per academic year (~6 months apart).
    Trimester programmes use three terms (~4 months apart).
    """
    if sem is not None and getattr(sem, "start_date", None):
        return sem.start_date

    if program_batch is None or not getattr(program_batch, "start_date", None):
        return None

    terms_per_year = terms_per_year_for_program(program)
    months_each = months_per_term_for_program(program)
    term_index = term_index_from_position(
        year_of_study=getattr(sem, "year_of_study", None) if sem else None,
        term_number=getattr(sem, "term_number", None) if sem else None,
        order=getattr(sem, "order", None) if sem else None,
        terms_per_year=terms_per_year,
    )
    if term_index is None:
        return program_batch.start_date
    return _add_months(program_batch.start_date, term_index * months_each)


def default_billing_date_for_year_term(
    program,
    program_batch,
    year_of_study: int,
    term_number: int,
):
    """Default billing date for other fees keyed by curriculum year/term."""
    from Programs.models import Semester

    if program_batch is not None and getattr(program_batch, "pk", None):
        match = (
            Semester.objects.filter(
                program_batch_id=program_batch.pk,
                year_of_study=year_of_study,
                term_number=term_number,
                is_active=True,
            )
            .order_by("order", "id")
            .first()
        )
        if match is not None:
            resolved = default_billing_date_for_semester(match, program_batch, program)
            if resolved is not None:
                return resolved

    if program_batch is None or not getattr(program_batch, "start_date", None):
        return None

    terms_per_year = terms_per_year_for_program(program)
    months_each = months_per_term_for_program(program)
    term_index = term_index_from_position(
        year_of_study=year_of_study,
        term_number=term_number,
        order=None,
        terms_per_year=terms_per_year,
    )
    if term_index is None:
        return program_batch.start_date
    return _add_months(program_batch.start_date, term_index * months_each)


def effective_billing_date(rule) -> date | None:
    """Explicit billing_date on the rule, or a term-based default."""
    stored = getattr(rule, "billing_date", None)
    if stored is not None:
        return stored

    program = getattr(rule, "program", None)
    if program is None and getattr(rule, "program_id", None):
        from Programs.models import Program

        program = Program.objects.filter(pk=rule.program_id).first()
    if program is None and getattr(rule, "program_batch_id", None):
        pb = getattr(rule, "program_batch", None)
        if pb is not None and pb.program_id:
            program = pb.program

    program_batch = getattr(rule, "program_batch", None)
    semester = getattr(rule, "semester", None)

    if semester is not None and program is not None:
        pb = program_batch or getattr(semester, "program_batch", None)
        return default_billing_date_for_semester(semester, pb, program)

    py = getattr(rule, "payable_year_of_study", None)
    pt = getattr(rule, "payable_term_number", None)
    if py and pt and program is not None:
        return default_billing_date_for_year_term(program, program_batch, int(py), int(pt))

    return None


def billing_date_reached(rule) -> bool:
    effective = effective_billing_date(rule)
    if effective is None:
        return True
    return timezone.localdate() >= effective


def billing_date_iso(rule) -> str | None:
    effective = effective_billing_date(rule)
    if effective is None:
        return None
    return effective.isoformat()


def adhoc_charge_billing_date(charge) -> date | None:
    """
    Effective billing date for a manual/ad-hoc charge (StudentTuitionPayment,
    source='ad_hoc') that was tagged to a Semester — e.g. a course-exemption fee
    staff split across "Year 2 Term 1" / "Year 2 Term 2". Mirrors
    default_billing_date_for_semester so the charge only becomes due when that
    term actually starts, instead of the moment it was created.

    Charges with no semester tag (the historical default for ad-hoc fees like
    penalties/retakes) have no gate here and remain immediately due.
    """
    sem = getattr(charge, "semester", None)
    if sem is None:
        return None
    program_batch = getattr(sem, "program_batch", None)
    program = getattr(program_batch, "program", None) if program_batch else None
    if program is None:
        student = getattr(charge, "student", None)
        program = getattr(student, "admitted_program", None) if student else None
    return default_billing_date_for_semester(sem, program_batch, program)


def adhoc_charge_billing_reached(charge) -> bool:
    effective = adhoc_charge_billing_date(charge)
    if effective is None:
        return True
    return timezone.localdate() >= effective


def resolve_billing_date_on_save(
    *,
    billing_date,
    semester=None,
    program_batch=None,
    program=None,
    year_of_study: int | None = None,
    term_number: int | None = None,
) -> date | None:
    """Use explicit date from admin, otherwise the logical term default."""
    parsed = parse_billing_date(billing_date)
    if parsed is not None:
        return parsed
    if semester is not None and program is not None:
        return default_billing_date_for_semester(
            semester, program_batch or getattr(semester, "program_batch", None), program
        )
    if year_of_study and term_number and program is not None:
        return default_billing_date_for_year_term(
            program, program_batch, int(year_of_study), int(term_number)
        )
    return None

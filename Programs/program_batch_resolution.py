"""Resolve academic :class:`~Programs.models.ProgramBatch` for admission / enrollment.

Cohort offer window rules:
  - Both ``offer_start_date`` and ``offer_end_date`` set on the cohort → use those (override).
  - Both null on the cohort → use the applicant's admission intake (``admissions.Batch``) dates.
  - When no intake is supplied (admin lists), null cohort dates are treated as always in window;
    set cohort dates or pass ``admission_batch`` at admit time for intake-driven behaviour.
"""
from __future__ import annotations

from datetime import date

from django.db.models import Q
from django.utils import timezone

from admissions.utils.batch_offer_filters import dates_in_offer_window

from .models import ProgramBatch


def _today(today=None) -> date:
    return today if today is not None else timezone.now().date()


def effective_offer_dates(program_batch, admission_batch=None):
    """
    Return (start, end, source) where source is ``cohort``, ``intake``, or ``none``.
    """
    if (
        program_batch.offer_start_date is not None
        and program_batch.offer_end_date is not None
    ):
        return (
            program_batch.offer_start_date,
            program_batch.offer_end_date,
            "cohort",
        )
    if admission_batch is not None:
        return (
            admission_batch.offer_start_date,
            admission_batch.offer_end_date,
            "intake",
        )
    return None, None, "none"


def cohort_offer_is_active(program_batch, *, today=None, admission_batch=None) -> bool:
    if not program_batch.is_active:
        return False
    start, end, _ = effective_offer_dates(program_batch, admission_batch)
    return dates_in_offer_window(start, end, today=_today(today))


def program_batch_in_active_offer_window_q(*, today=None, admission_batch=None) -> Q:
    """
    ORM filter for cohorts that are in an active offer window.

    With ``admission_batch``, null-date cohorts match only when the intake window is active.
    """
    today = _today(today)
    explicit = Q(offer_start_date__isnull=False, offer_end_date__isnull=False)
    explicit_window = explicit & Q(offer_start_date__lte=today) & Q(offer_end_date__gte=today)
    inherit = Q(offer_start_date__isnull=True, offer_end_date__isnull=True)

    if admission_batch is None:
        return explicit_window | inherit

    if not dates_in_offer_window(
        admission_batch.offer_start_date,
        admission_batch.offer_end_date,
        today=today,
    ):
        return explicit_window

    return explicit_window | inherit


def admission_program_batch_options_qs(program, *, today=None, admission_batch=None):
    """Active cohorts in offer window for a programme (queryset, not evaluated)."""
    if program is None:
        return ProgramBatch.objects.none()
    pid = program.pk if hasattr(program, "pk") else program
    return (
        ProgramBatch.objects.filter(program_id=pid, is_active=True)
        .filter(program_batch_in_active_offer_window_q(today=today, admission_batch=admission_batch))
        .order_by("-start_date", "name")
    )


def resolve_default_program_batch_for_program(
    program, *, today=None, admission_batch=None
) -> ProgramBatch | None:
    """First cohort from :func:`admission_program_batch_options_qs`, or ``None``."""
    return admission_program_batch_options_qs(
        program, today=today, admission_batch=admission_batch
    ).first()


def program_batch_offer_api_fields(program_batch, *, today=None, admission_batch=None) -> dict:
    """Extra read-only fields for APIs (effective dates + source)."""
    start, end, source = effective_offer_dates(program_batch, admission_batch)
    return {
        "offer_start_date": (
            program_batch.offer_start_date.isoformat()
            if program_batch.offer_start_date
            else None
        ),
        "offer_end_date": (
            program_batch.offer_end_date.isoformat()
            if program_batch.offer_end_date
            else None
        ),
        "effective_offer_start_date": start.isoformat() if start else None,
        "effective_offer_end_date": end.isoformat() if end else None,
        "offer_dates_source": source,
        "is_offer_active": cohort_offer_is_active(
            program_batch, today=today, admission_batch=admission_batch
        ),
    }


def format_program_batch_display(program_batch: ProgramBatch | None) -> str:
    """Human-readable academic cohort label (not admission intake)."""
    if program_batch is None:
        return ""
    name = (program_batch.name or "").strip()
    year = (getattr(program_batch, "academic_year", None) or "").strip()
    if name and year and year not in name:
        return f"{name} ({year})"
    return name or year or "—"


def resolve_student_academic_cohort(
    admitted_student,
    enrollment=None,
) -> ProgramBatch | None:
    """
    Academic cohort for display: enrollment batch → intended cohort → default offer cohort.
    Never returns admissions.Batch (intake).
    """
    if enrollment is not None and getattr(enrollment, "program_batch_id", None):
        return enrollment.program_batch
    intended = getattr(admitted_student, "intended_program_batch", None)
    if intended is not None and getattr(intended, "pk", None):
        return intended
    program = getattr(admitted_student, "admitted_program", None)
    if program is None and getattr(admitted_student, "admitted_program_id", None):
        from .models import Program

        program = Program.objects.filter(pk=admitted_student.admitted_program_id).first()
    admission_batch = getattr(admitted_student, "admitted_batch", None)
    return resolve_default_program_batch_for_program(
        program,
        admission_batch=admission_batch,
    )


def academic_cohort_display_for_student(admitted_student, enrollment=None) -> tuple[str, str | None]:
    """
    Returns (academic_cohort_label, admission_intake_label).
    Intake is only returned when no academic cohort could be resolved.
    """
    cohort = resolve_student_academic_cohort(admitted_student, enrollment)
    if cohort:
        return format_program_batch_display(cohort), str(admitted_student.admitted_batch)
    return "Not assigned yet", str(admitted_student.admitted_batch)

"""Which programmes may be attached to an admission intake."""
from __future__ import annotations

from django.db.models import QuerySet

from Programs.models import Program, ProgramBatch
from Programs.program_batch_resolution import program_batch_in_active_offer_window_q


def program_ids_with_active_cohort_offer(*, today=None) -> set[int]:
    """
    Programmes with at least one active ProgramBatch in an open offer window today.
    Cohorts with null offer dates count as open (same rule as admit-time resolution).
    """
    window_q = program_batch_in_active_offer_window_q(today=today, admission_batch=None)
    return set(
        ProgramBatch.objects.filter(is_active=True)
        .filter(window_q)
        .values_list("program_id", flat=True)
        .distinct()
    )


def validate_intake_program_selection(
    program_ids: list[int],
    *,
    grandfather_ids: set[int] | None = None,
) -> list[str]:
    """
    Return human-readable errors for programmes that cannot be newly added to an intake.
    ``grandfather_ids`` keeps programmes already on an intake when editing dates only.
    """
    if not program_ids:
        return ["Select at least one programme."]

    grandfather = set(grandfather_ids or [])
    eligible = program_ids_with_active_cohort_offer()
    blocked = [pid for pid in program_ids if pid not in eligible and pid not in grandfather]
    if not blocked:
        return []

    names = list(
        Program.objects.filter(id__in=blocked)
        .order_by("name")
        .values_list("name", flat=True)
    )
    if len(names) == 1:
        return [
            f"{names[0]} has no active academic cohort in offer. "
            "Create or activate a programme batch under Batches & timetables first."
        ]
    preview = ", ".join(names[:5])
    suffix = f" (+{len(names) - 5} more)" if len(names) > 5 else ""
    return [
        f"The following programmes have no active cohort in offer: {preview}{suffix}. "
        "Configure programme batches before adding them to an intake."
    ]


def applicant_selectable_programs_qs(
    batch,
    *,
    campus_id=None,
    level_id=None,
    today=None,
) -> QuerySet:
    """
    Programmes on an intake that applicants may choose: on the intake, active,
    with an active academic cohort in offer, optionally filtered by campus/level.
    """
    if batch is None:
        return Program.objects.none()

    eligible = program_ids_with_active_cohort_offer(today=today)
    qs = (
        batch.programs.filter(is_active=True, id__in=eligible)
        .select_related("faculty", "academic_level")
        .prefetch_related("campuses")
        .order_by("name")
    )
    if level_id:
        qs = qs.filter(academic_level_id=level_id)
    if campus_id:
        qs = qs.filter(campuses__id=campus_id)
    return qs.distinct()


def validate_applicant_program_selection(
    program_ids: list[int],
    batch,
    *,
    campus_id=None,
    level_id=None,
    today=None,
) -> list[str]:
    """Return errors when programme ids are not open for applicant selection."""
    if not program_ids:
        return ["Select at least one programme."]
    if batch is None:
        return ["No admission intake is configured for this application."]

    selectable = set(
        applicant_selectable_programs_qs(
            batch,
            campus_id=campus_id,
            level_id=level_id,
            today=today,
        ).values_list("id", flat=True)
    )
    blocked = [pid for pid in program_ids if pid not in selectable]
    if not blocked:
        return []

    names = list(
        Program.objects.filter(id__in=blocked)
        .order_by("name")
        .values_list("name", flat=True)
    )
    if len(names) == 1:
        return [
            f"{names[0]} is not open for admission on this intake. "
            "Choose a programme with an active academic cohort."
        ]
    preview = ", ".join(names[:5])
    suffix = f" (+{len(names) - 5} more)" if len(names) > 5 else ""
    return [
        f"The following programmes are not open for admission: {preview}{suffix}. "
        "Choose programmes with active academic cohorts."
    ]


def staff_direct_entry_programs_qs(
    batch,
    *,
    campus_id=None,
    level_id=None,
) -> QuerySet:
    """Programmes on an intake that staff may use for direct entry (cohort not required)."""
    if batch is None:
        return Program.objects.none()

    qs = (
        batch.programs.filter(is_active=True)
        .select_related("faculty", "academic_level")
        .prefetch_related("campuses")
        .order_by("name")
    )
    if level_id:
        qs = qs.filter(academic_level_id=level_id)
    if campus_id:
        qs = qs.filter(campuses__id=campus_id)
    return qs.distinct()


def validate_staff_direct_entry_program_selection(
    program_ids: list[int],
    batch,
    *,
    campus_id=None,
    level_id=None,
) -> list[str]:
    """Return errors when programme ids are not on the intake for direct entry."""
    if not program_ids:
        return ["Select at least one programme."]
    if batch is None:
        return ["No admission intake is configured."]

    selectable = set(
        staff_direct_entry_programs_qs(
            batch,
            campus_id=campus_id,
            level_id=level_id,
        ).values_list("id", flat=True)
    )
    blocked = [pid for pid in program_ids if pid not in selectable]
    if not blocked:
        return []

    names = list(
        Program.objects.filter(id__in=blocked)
        .order_by("name")
        .values_list("name", flat=True)
    )
    if len(names) == 1:
        return [
            f"{names[0]} is not offered on this intake for the selected campus and academic level."
        ]
    preview = ", ".join(names[:5])
    suffix = f" (+{len(names) - 5} more)" if len(names) > 5 else ""
    return [
        f"The following programmes are not on this intake for the selected campus/level: {preview}{suffix}."
    ]

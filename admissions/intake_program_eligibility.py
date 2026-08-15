"""Which programmes may be attached to an admission intake."""
from __future__ import annotations

from django.db.models import QuerySet

from Programs.models import Program, ProgramBatch


def program_ids_with_active_cohort(*, today=None) -> set[int]:
    """
    Programmes with at least one active ProgramBatch (academic cohort).

    Offer timing is controlled on the intake, not on the cohort.
    """
    del today  # reserved for future date-scoped cohort rules
    return set(
        ProgramBatch.objects.filter(is_active=True)
        .values_list("program_id", flat=True)
        .distinct()
    )


# Backwards-compatible alias used by older call sites / docs.
program_ids_with_active_cohort_offer = program_ids_with_active_cohort


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
    eligible = program_ids_with_active_cohort()
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
            f"{names[0]} has no active academic cohort. "
            "Create or activate a programme batch under Batches & timetables first."
        ]
    preview = ", ".join(names[:5])
    suffix = f" (+{len(names) - 5} more)" if len(names) > 5 else ""
    return [
        f"The following programmes have no active academic cohort: {preview}{suffix}. "
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
    with an active academic cohort. Offer timing is enforced by the intake window.
    """
    if batch is None:
        return Program.objects.none()

    eligible = program_ids_with_active_cohort(today=today)
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
    grandfather_ids: set[int] | None = None,
    require_on_intake: bool = True,
) -> list[str]:
    """Return errors when programme ids are not allowed for staff selection.

    Direct entry keeps ``require_on_intake=True`` (must be on the intake).
    Change of course on an existing application uses ``require_on_intake=False``
    so staff can move a student to another active programme at the campus.
    """
    if not program_ids:
        return ["Select at least one programme."]

    grandfather = set(grandfather_ids or ())
    if require_on_intake:
        if batch is None:
            return ["No admission intake is configured."]
        selectable = set(
            staff_direct_entry_programs_qs(
                batch,
                campus_id=campus_id,
                level_id=level_id,
            ).values_list("id", flat=True)
        )
        msg_one = (
            "{name} is not offered on this intake for the selected campus and academic level."
        )
        msg_many = (
            "The following programmes are not on this intake for the selected campus/level: {preview}{suffix}."
        )
    else:
        qs = Program.objects.filter(is_active=True)
        if campus_id:
            from django.db.models import Count, Q

            qs = qs.annotate(_campus_n=Count("campuses")).filter(
                Q(campuses__id=campus_id) | Q(_campus_n=0)
            )
        selectable = set(qs.values_list("id", flat=True).distinct())
        msg_one = "{name} is not offered at the selected campus (or is inactive)."
        msg_many = (
            "The following programmes are not offered at the selected campus: {preview}{suffix}."
        )

    blocked = [
        pid for pid in program_ids if pid not in selectable and pid not in grandfather
    ]
    if not blocked:
        return []

    names = list(
        Program.objects.filter(id__in=blocked)
        .order_by("name")
        .values_list("name", flat=True)
    )
    if len(names) == 1:
        return [msg_one.format(name=names[0])]
    preview = ", ".join(names[:5])
    suffix = f" (+{len(names) - 5} more)" if len(names) > 5 else ""
    return [msg_many.format(preview=preview, suffix=suffix)]

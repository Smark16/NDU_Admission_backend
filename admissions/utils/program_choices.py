"""Sync and validate ApplicationProgramChoice rows."""
from __future__ import annotations

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.utils import timezone

from Programs.models import Program

# Applicants may update/confirm while the application is still in the review pipeline.
PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT = "applicant"
PROGRAM_CHOICE_CONFIRMED_BY_STAFF = "staff"

APPLICANT_PROGRAM_CHOICE_STATUSES = frozenset(
    {
        "submitted",
        "under_review",
        "revoked",
        "accepted",
        "approved",
    }
)


def applicant_may_edit_program_choices(application) -> bool:
    status = (application.status or "").strip().lower()
    return status in APPLICANT_PROGRAM_CHOICE_STATUSES


def _choice_model():
    return apps.get_model("admissions", "ApplicationProgramChoice")


def _order_field_name(choice_model=None):
    choice_model = choice_model or _choice_model()
    for name in ("preference", "rank", "choice_order", "order", "position", "sort_order"):
        try:
            choice_model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        return name
    return None


@transaction.atomic
def sync_application_program_choices(
    application,
    program_ids: list[int],
    *,
    staff: bool = False,
    campus_id=None,
    grandfather_ids: set[int] | None = None,
) -> None:
    """Replace ordered programme choices and keep legacy M2M in sync."""
    if not program_ids:
        raise ValueError("At least one programme is required.")

    if staff:
        assert_staff_may_select_programs_for_direct_entry(
            application,
            program_ids,
            campus_id=campus_id,
            level_id=None,
            grandfather_ids=grandfather_ids,
        )
    else:
        assert_applicant_may_select_programs(application, program_ids)

    unique_ids = []
    seen = set()
    for raw in program_ids:
        pid = int(raw)
        if pid in seen:
            continue
        seen.add(pid)
        unique_ids.append(pid)

    program_qs = Program.objects.filter(id__in=unique_ids)
    if program_qs.count() != len(unique_ids):
        raise ValueError("One or more selected programmes are invalid.")

    try:
        application._meta.get_field("programs")
        application.programs.set(program_qs)
    except FieldDoesNotExist:
        pass

    Choice = _choice_model()
    order_field = _order_field_name(Choice)
    application.program_choices.all().delete()
    rows = []
    for idx, pid in enumerate(unique_ids, start=1):
        kwargs = {"application": application, "program_id": pid}
        if order_field:
            kwargs[order_field] = idx
        rows.append(Choice(**kwargs))
    Choice.objects.bulk_create(rows)


def sync_application_academic_level_from_programs(
    application, program_ids: list[int]
) -> tuple[bool, str | None]:
    """
    Set application.academic_level from the first programme choice.
    All selected programmes must share the same academic level.
    Returns (changed, new_level_name).
    """
    if not program_ids:
        return False, None

    programs = list(
        Program.objects.filter(id__in=program_ids).select_related("academic_level")
    )
    by_id = {p.id: p for p in programs}
    ordered = [by_id[pid] for pid in program_ids if pid in by_id]
    if not ordered:
        return False, None

    level_ids = {p.academic_level_id for p in ordered if p.academic_level_id}
    if len(level_ids) > 1:
        raise ValueError(
            "All selected programmes must be at the same academic level (e.g. all Degree or all Diploma)."
        )

    primary = ordered[0]
    if not primary.academic_level_id:
        return False, None

    changed = application.academic_level_id != primary.academic_level_id
    application.academic_level = primary.academic_level
    level_name = primary.academic_level.name if primary.academic_level else None
    return changed, level_name


def clear_program_choices_confirmation(application, *, save: bool = True) -> None:
    application.program_choices_confirmed_at = None
    application.program_choices_confirmed_by = ""
    if save:
        application.save(
            update_fields=[
                "program_choices_confirmed_at",
                "program_choices_confirmed_by",
                "updated_at",
            ]
        )


def mark_program_choices_confirmed(application, *, save: bool = True) -> None:
    """Applicant clicked Confirm in the portal."""
    application.program_choices_confirmed_at = timezone.now()
    application.program_choices_confirmed_by = PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT
    if save:
        application.save(
            update_fields=[
                "program_choices_confirmed_at",
                "program_choices_confirmed_by",
                "updated_at",
            ]
        )


def mark_program_choices_settled_by_admin(application, *, save: bool = True) -> None:
    """Staff saved programme choices via change programme (not applicant confirm)."""
    application.program_choices_confirmed_at = timezone.now()
    application.program_choices_confirmed_by = PROGRAM_CHOICE_CONFIRMED_BY_STAFF
    if save:
        application.save(
            update_fields=[
                "program_choices_confirmed_at",
                "program_choices_confirmed_by",
                "updated_at",
            ]
        )


def applicant_confirmed_program_choices(application) -> bool:
    return bool(application.program_choices_confirmed_at) and (
        (application.program_choices_confirmed_by or "").strip().lower()
        == PROGRAM_CHOICE_CONFIRMED_BY_APPLICANT
    )


def program_options_for_application(application) -> list[dict]:
    """Programmes applicants may choose: intake + campus/level + active cohort in offer."""
    from admissions.intake_program_eligibility import applicant_selectable_programs_qs

    batch = getattr(application, "batch", None)
    if batch is None:
        return []
    out = []
    for program in applicant_selectable_programs_qs(
        batch,
        campus_id=application.campus_id,
        level_id=application.academic_level_id,
    ):
        out.append(
            {
                "id": program.id,
                "name": program.name,
                "code": getattr(program, "code", "") or "",
            }
        )
    return out


_UNSET = object()


def assert_staff_may_select_programs_for_direct_entry(
    application,
    program_ids: list[int],
    *,
    campus_id=None,
    level_id=_UNSET,
    grandfather_ids: set[int] | None = None,
) -> None:
    """Raise ValueError when programme ids are invalid for staff direct entry."""
    from admissions.intake_program_eligibility import validate_staff_direct_entry_program_selection

    batch = getattr(application, "batch", None)
    if batch is None and getattr(application, "batch_id", None):
        from admissions.models import Batch

        batch = Batch.objects.filter(pk=application.batch_id).first()

    effective_campus = application.campus_id if campus_id is None else campus_id
    effective_level = (
        application.academic_level_id if level_id is _UNSET else level_id
    )

    messages = validate_staff_direct_entry_program_selection(
        program_ids,
        batch,
        campus_id=effective_campus,
        level_id=effective_level,
        grandfather_ids=grandfather_ids,
    )
    if messages:
        raise ValueError(messages[0])


def assert_applicant_may_select_programs(application, program_ids: list[int]) -> None:
    """Raise ValueError when programme ids are not open for this applicant."""
    from admissions.intake_program_eligibility import validate_applicant_program_selection

    messages = validate_applicant_program_selection(
        program_ids,
        getattr(application, "batch", None),
        campus_id=application.campus_id,
        level_id=application.academic_level_id,
    )
    if messages:
        raise ValueError(messages[0])


def parse_program_id_list(programs_input) -> list[int]:
    """Parse programme id list from JSON string, list, or scalar."""
    import json

    if not programs_input:
        return []
    if isinstance(programs_input, str):
        try:
            programs_input = json.loads(programs_input)
        except (json.JSONDecodeError, TypeError):
            return []
    if not isinstance(programs_input, (list, tuple)):
        programs_input = [programs_input]

    out: list[int] = []
    seen: set[int] = set()
    for raw in programs_input:
        try:
            pid = int(raw)
        except (TypeError, ValueError):
            continue
        if pid <= 0 or pid in seen:
            continue
        seen.add(pid)
        out.append(pid)
    return out

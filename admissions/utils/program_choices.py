"""Sync and validate ApplicationProgramChoice rows."""
from __future__ import annotations

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist
from django.db import transaction
from django.utils import timezone

from Programs.models import Program

# Applicants may update/confirm while the application is still in the review pipeline.
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
def sync_application_program_choices(application, program_ids: list[int]) -> None:
    """Replace ordered programme choices and keep legacy M2M in sync."""
    if not program_ids:
        raise ValueError("At least one programme is required.")

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


def clear_program_choices_confirmation(application, *, save: bool = True) -> None:
    application.program_choices_confirmed_at = None
    if save:
        application.save(update_fields=["program_choices_confirmed_at", "updated_at"])


def mark_program_choices_confirmed(application, *, save: bool = True) -> None:
    application.program_choices_confirmed_at = timezone.now()
    if save:
        application.save(update_fields=["program_choices_confirmed_at", "updated_at"])


def program_options_for_application(application) -> list[dict]:
    """Programmes on the application's batch that match campus + academic level."""
    batch = getattr(application, "batch", None)
    if batch is None:
        return []
    campus_id = application.campus_id
    level_id = application.academic_level_id
    out = []
    for program in batch.programs.prefetch_related("campuses").all():
        if level_id and program.academic_level_id != level_id:
            continue
        if campus_id and not program.campuses.filter(pk=campus_id).exists():
            continue
        out.append(
            {
                "id": program.id,
                "name": program.name,
                "code": getattr(program, "code", "") or "",
            }
        )
    out.sort(key=lambda x: x["name"].lower())
    return out

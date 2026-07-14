"""
Detect programme-choice rows that may be wrong after the Application.programs →
ApplicationProgramChoice migration (bulk-cloned template IDs, etc.).

Used by bulk verification email, applicant confirm UI, and admin list warnings.
"""
from __future__ import annotations

from django.apps import apps

# Programme ID triplets copied onto many applications during a bad bulk update.
# See bulk_send_program_choice_verification.CLONED_SIGNATURES.
SUSPECT_PROGRAM_ID_SIGNATURES: frozenset[tuple[int, ...]] = frozenset(
    {
        (28, 29, 30),
        (162, 163, 164),
        (181, 190, 195),
        (154, 153, 210),
        (31, 77, 76),
    }
)


def _choice_order_field(choice_model) -> str | None:
    for name in ("choice_order", "preference", "rank", "order", "position", "sort_order"):
        try:
            choice_model._meta.get_field(name)
        except Exception:
            continue
        return name
    return None


def ordered_program_ids_for_application(application) -> tuple[int, ...]:
    """Return programme IDs in choice order for integrity checks."""
    Choice = apps.get_model("admissions", "ApplicationProgramChoice")
    order_field = _choice_order_field(Choice)

    choices = getattr(application, "prefetched_program_choices", None)
    if choices is None:
        choices = list(application.program_choices.all())
    else:
        choices = list(choices)

    if not choices:
        return ()

    if order_field:
        choices.sort(key=lambda c: getattr(c, order_field, 0) or 0)
    return tuple(c.program_id for c in choices if c.program_id)


def application_has_suspect_program_choices(application) -> bool:
    """
    True when choices match a known bad bulk-clone signature from the DB incident.
    Does not prove data is correct when False — staff should still spot-check.
    """
    sig = ordered_program_ids_for_application(application)
    if not sig:
        return False
    return sig in SUSPECT_PROGRAM_ID_SIGNATURES


def application_ids_with_suspect_program_choices(application_ids=None) -> set[int]:
    """All application IDs whose current choices match a suspect signature."""
    Choice = apps.get_model("admissions", "ApplicationProgramChoice")
    order_field = _choice_order_field(Choice)
    if not order_field:
        return set()

    qs = Choice.objects.values_list("application_id", "program_id", order_field)
    if application_ids is not None:
        qs = qs.filter(application_id__in=application_ids)

    by_app: dict[int, list[tuple[int, int]]] = {}
    for aid, pid, ord_val in qs:
        by_app.setdefault(aid, []).append((ord_val or 0, pid))

    out: set[int] = set()
    for aid, pairs in by_app.items():
        sig = tuple(pid for _, pid in sorted(pairs))
        if sig in SUSPECT_PROGRAM_ID_SIGNATURES:
            out.add(aid)
    return out

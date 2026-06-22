"""Query helpers for admissions.Batch (intake periods).

Intakes may set optional ``offer_start_date`` / ``offer_end_date``. When either is
set, ``batch_offer_window_q()`` restricts rows so only intakes whose offer window
includes *today* are included — mirroring the date semantics used for
``Programs.ProgramBatch`` offer windows. If **both** dates are null, the intake is
**never** excluded by this helper (unchanged behaviour for legacy rows).
"""
from django.db.models import Q
from django.utils import timezone


def dates_in_offer_window(start, end, *, today=None) -> bool:
    """True when *today* is inside [start, end], treating null bounds as open."""
    if today is None:
        today = timezone.now().date()
    if start is None and end is None:
        return True
    if start is not None and today < start:
        return False
    if end is not None and today > end:
        return False
    return True


def batch_offer_window_q():
    """
    Intake offer-window filter: same date logic as cohort resolution.

    - Both dates null → row matches (always visible for offer purposes).
    - Otherwise → today must be on or after start (if set) and on or before end (if set).
    """
    today = timezone.now().date()
    return (
        (Q(offer_start_date__isnull=True) & Q(offer_end_date__isnull=True))
        | (
            (Q(offer_start_date__isnull=True) | Q(offer_start_date__lte=today))
            & (Q(offer_end_date__isnull=True) | Q(offer_end_date__gte=today))
        )
    )


def open_application_window_q(*, today=None):
    """Intakes whose applicant application window includes *today*."""
    today = today or timezone.now().date()
    return Q(application_start_date__lte=today, application_end_date__gte=today)


def resolve_active_application_batch(*, today=None):
    """
    Return the portal's active application intake, or ``None``.

    When several intakes are open, prefer non-QA production rows, then the oldest
    by ``created_at`` (stable choice if only one should be active in production).
    """
    from admissions.models import Batch

    today = today or timezone.now().date()
    base = (
        Batch.objects.filter(is_active=True)
        .filter(batch_offer_window_q())
        .filter(open_application_window_q(today=today))
        .order_by("created_at")
    )
    batch = (
        base.exclude(code__istartswith="QA-")
        .exclude(name__icontains="[QA-INTAKE-BATCH]")
        .first()
    )
    return batch or base.first()


def resolve_admission_intake_batch(
    *,
    batch_id: int | None = None,
    application_id: int | None = None,
):
    """
    Resolve admissions.Batch (intake) for admit / reg-no generation.

    Priority:
      1. Explicit batch_id from client
      2. Application's intake batch (when application_id given)
      3. Active admission window intake
      4. Active application window intake
      5. Latest active intake (fallback)
    """
    from admissions.models import Application, Batch

    if batch_id is not None:
        return Batch.objects.get(pk=batch_id)

    if application_id is not None:
        app = (
            Application.objects.select_related("batch")
            .filter(pk=application_id)
            .first()
        )
        if app is not None and app.batch_id:
            return app.batch

    now = timezone.now().date()
    base = (
        Batch.objects.filter(is_active=True)
        .filter(batch_offer_window_q())
        .filter(
            Q(application_start_date__lte=now, application_end_date__gte=now)
            | Q(admission_start_date__lte=now, admission_end_date__gte=now)
        )
        .order_by("created_at")
    )
    batch = (
        base.exclude(code__istartswith="QA-")
        .exclude(name__icontains="[QA-INTAKE-BATCH]")
        .first()
    )
    if batch is not None:
        return batch

    batch = base.first()
    if batch is not None:
        return batch

    batch = resolve_active_application_batch(today=now)
    if batch is not None:
        return batch

    return (
        Batch.objects.filter(is_active=True)
        .order_by("-created_at")
        .first()
    )

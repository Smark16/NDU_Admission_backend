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

"""Query helpers for admissions.Batch (intake periods).

Intakes may set optional ``offer_start_date`` / ``offer_end_date``. When either is
set, ``batch_offer_window_q()`` restricts rows so only intakes whose offer window
includes *today* are included — mirroring the date semantics used for
``Programs.ProgramBatch`` offer windows. If **both** dates are null, the intake is
**never** excluded by this helper (unchanged behaviour for legacy rows).
"""
from django.db.models import Q
from django.utils import timezone


def batch_offer_window_q():
    """
    Intake offer-window filter: same date logic as ``program_batch_in_active_offer_window_q``
    in ``Programs.program_batch_resolution`` (field names match ``admissions.Batch``).

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

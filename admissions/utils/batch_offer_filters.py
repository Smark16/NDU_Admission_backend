"""Query helpers for admissions.Batch optional offer validity window."""
from django.db.models import Q
from django.utils import timezone


def batch_offer_window_q():
    """
    Restrict to batches whose offer window includes today, if dates are set.
    Rows with both offer dates null are always included.
    """
    today = timezone.now().date()
    return (
        (Q(offer_end_date__isnull=True) | Q(offer_end_date__gte=today))
        & (Q(offer_start_date__isnull=True) | Q(offer_start_date__lte=today))
    )

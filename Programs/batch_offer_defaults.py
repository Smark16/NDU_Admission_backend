"""Admission offer windows for :class:`~Programs.models.ProgramBatch`.

Offer timing is controlled on the admission Intake. Cohort offer dates should
normally stay null so admit pickers inherit the intake window. Explicit cohort
dates are still accepted for API/legacy compatibility but are no longer inferred
from academic start/end.
"""
from __future__ import annotations

from datetime import date


def resolve_program_batch_offer_dates(
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    offer_start_date: date | None = None,
    offer_end_date: date | None = None,
) -> tuple[date | None, date | None]:
    """
    Return explicit offer dates when both are provided; otherwise null.

    ``start_date`` / ``end_date`` are ignored (kept for call-site compatibility).
    """
    del start_date, end_date
    if offer_start_date is not None and offer_end_date is not None:
        return offer_start_date, offer_end_date
    return None, None


def offer_dates_missing_or_partial(
    offer_start: date | None,
    offer_end: date | None,
) -> bool:
    """True when both are empty or only one is set."""
    if offer_start is None and offer_end is None:
        return True
    if offer_start is None or offer_end is None:
        return True
    return False

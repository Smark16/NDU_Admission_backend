"""Default admission offer windows for :class:`~Programs.models.ProgramBatch`.

When cohort ``offer_start_date`` / ``offer_end_date`` are blank, admit pickers
inherit the application intake window — which often hides cohorts. These helpers
derive explicit offer dates from cohort ``start_date`` / ``end_date``.
"""
from __future__ import annotations

from datetime import date, timedelta


def infer_program_batch_offer_dates(
    start_date: date,
    end_date: date | None = None,
) -> tuple[date, date]:
    """
    Place students into this cohort while its academic run is relevant.

    - ``offer_start`` = cohort ``start_date``
    - ``offer_end`` = cohort ``end_date`` when set and not before start;
      otherwise 31 Dec of the start year, or start + 365 days if that is earlier.
    """
    if start_date is None:
        raise ValueError("start_date is required to infer offer dates")

    offer_start = start_date
    if end_date is not None and end_date >= offer_start:
        offer_end = end_date
    else:
        offer_end = date(start_date.year, 12, 31)
        if offer_end < offer_start:
            offer_end = offer_start + timedelta(days=365)
    return offer_start, offer_end


def offer_dates_missing_or_partial(
    offer_start: date | None,
    offer_end: date | None,
) -> bool:
    """True when both are empty or only one is set (invalid for admit filtering)."""
    if offer_start is None and offer_end is None:
        return True
    if offer_start is None or offer_end is None:
        return True
    return False


def resolve_program_batch_offer_dates(
    *,
    start_date: date,
    end_date: date | None,
    offer_start_date: date | None,
    offer_end_date: date | None,
) -> tuple[date, date]:
    """
    Return explicit offer dates: use provided pair when both set; otherwise infer.
    """
    if offer_start_date is not None and offer_end_date is not None:
        return offer_start_date, offer_end_date
    return infer_program_batch_offer_dates(start_date, end_date)

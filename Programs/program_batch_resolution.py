"""Resolve academic :class:`~Programs.models.ProgramBatch` for admission / enrollment.

Uses the same rules as the admit-officer batch list: **active** cohorts whose optional
offer window includes *today* (or with no offer dates set), ordered by latest
``start_date`` then name.
"""
from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from .models import ProgramBatch


def program_batch_in_active_offer_window_q(*, today=None) -> Q:
    if today is None:
        today = timezone.now().date()
    return (
        (Q(offer_start_date__isnull=True) & Q(offer_end_date__isnull=True))
        | (
            (Q(offer_start_date__isnull=True) | Q(offer_start_date__lte=today))
            & (Q(offer_end_date__isnull=True) | Q(offer_end_date__gte=today))
        )
    )


def admission_program_batch_options_qs(program, *, today=None):
    """Active cohorts in offer window for a programme ( queryset, not evaluated )."""
    if program is None:
        return ProgramBatch.objects.none()
    pid = program.pk if hasattr(program, "pk") else program
    if today is None:
        today = timezone.now().date()
    return (
        ProgramBatch.objects.filter(program_id=pid, is_active=True)
        .filter(program_batch_in_active_offer_window_q(today=today))
        .order_by("-start_date", "name")
    )


def resolve_default_program_batch_for_program(program, *, today=None) -> ProgramBatch | None:
    """First cohort from :func:`admission_program_batch_options_qs`, or ``None``."""
    return admission_program_batch_options_qs(program, today=today).first()

"""
Resolve ordered :class:`~Programs.models.Program` rows for an :class:`~admissions.models.Application`.

Uses :class:`~admissions.models.ApplicationProgramChoice` when that model exists and has rows;
otherwise falls back to the legacy ``Application.programs`` M2M (if present on the schema).
"""
from __future__ import annotations

from typing import List

from django.apps import apps
from django.core.exceptions import FieldDoesNotExist


def ordered_programs_for_application(application) -> List:
    """Return ``Program`` model instances in display order (may be empty)."""
    programs = _programs_from_choice_rows(application)
    if programs:
        return programs
    try:
        application._meta.get_field("programs")
    except FieldDoesNotExist:
        return []
    return list(
        application.programs.select_related("faculty").prefetch_related("campuses").order_by("pk").all()
    )


def _programs_from_choice_rows(application) -> List:
    try:
        Choice = apps.get_model("admissions", "ApplicationProgramChoice")
    except LookupError:
        return []
    if not hasattr(application, "program_choices"):
        return []
    qs = application.program_choices.select_related(
        "program", "program__faculty"
    ).prefetch_related("program__campuses").all()
    if not qs.exists():
        return []
    order_field = _first_order_field(Choice)
    if order_field:
        qs = qs.order_by(order_field, "pk")
    else:
        qs = qs.order_by("pk")
    out = []
    for row in qs:
        prog = getattr(row, "program", None)
        if prog is not None:
            out.append(prog)
    return out


def _first_order_field(choice_model):
    for name in (
        "preference",
        "rank",
        "choice_order",
        "order",
        "position",
        "sort_order",
    ):
        try:
            choice_model._meta.get_field(name)
        except FieldDoesNotExist:
            continue
        return name
    return None

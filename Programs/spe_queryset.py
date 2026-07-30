"""Safe StudentProgrammeEnrollment querysets for list/detail screens.

``teaching_section`` (Programs.0023) is often missing on production when the
migration was faked without DDL. Any ``select_related("programme_enrollment")``
that pulls all SPE columns will 500. Prefer these helpers instead.
"""
from __future__ import annotations

from django.db.models import Prefetch


def programme_enrollment_qs_for_lists():
    """SPE rows without teaching_section column (safe when 0023 DDL is missing)."""
    from Programs.models import StudentProgrammeEnrollment

    return StudentProgrammeEnrollment.objects.select_related("program_batch").defer(
        "teaching_section"
    )


def prefetch_programme_enrollment_for_lists() -> Prefetch:
    return Prefetch("programme_enrollment", queryset=programme_enrollment_qs_for_lists())

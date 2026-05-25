"""Resolve degree class of award from CGPA and academic level."""
from __future__ import annotations

from decimal import Decimal

from admissions.models import AcademicLevel, AdmittedStudent

from ..models import AwardClassBand, AwardClassificationScheme
from .grade_scale_resolver import academic_level_for_student


def lookup_award_class(cgpa, bands) -> str:
    if cgpa is None:
        return ""
    value = Decimal(str(cgpa))
    for band in sorted(bands, key=lambda b: (-b.min_cgpa, b.order)):
        if value >= band.min_cgpa:
            return band.title
    return ""


def resolve_award_classification_scheme(
    *,
    student: AdmittedStudent | None = None,
    academic_level: AcademicLevel | None = None,
    academic_level_id: int | None = None,
) -> AwardClassificationScheme | None:
    level = academic_level
    if level is None and academic_level_id is not None:
        level = AcademicLevel.objects.filter(pk=academic_level_id).first()
    if level is None and student is not None:
        level = academic_level_for_student(student)

    if level is not None:
        scheme = AwardClassificationScheme.get_for_academic_level(level)
        if scheme:
            return scheme

    return AwardClassificationScheme.get_active_default()


def resolve_award_class(
    cgpa,
    *,
    student: AdmittedStudent | None = None,
    academic_level: AcademicLevel | None = None,
    academic_level_id: int | None = None,
) -> str:
    scheme = resolve_award_classification_scheme(
        student=student,
        academic_level=academic_level,
        academic_level_id=academic_level_id,
    )
    if not scheme:
        return ""
    bands = list(scheme.bands.all())
    if not bands:
        return ""
    return lookup_award_class(cgpa, bands)

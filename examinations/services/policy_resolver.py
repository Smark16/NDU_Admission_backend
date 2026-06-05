"""Resolve which AssessmentPolicy applies for a course or enrollment."""
from __future__ import annotations

from admissions.models import AcademicLevel
from Programs.models import CourseUnit, StudentCourseUnitEnrollment

from ..models import AssessmentPolicy


def academic_level_for_course_unit(course_unit: CourseUnit) -> AcademicLevel | None:
    if not course_unit.program_batch_id:
        return None
    program = getattr(course_unit.program_batch, "program", None)
    if program is None:
        return None
    return program.academic_level


def academic_level_for_enrollment(
    enrollment: StudentCourseUnitEnrollment,
) -> AcademicLevel | None:
    return academic_level_for_course_unit(enrollment.course_unit)


def resolve_assessment_policy(
    *,
    enrollment: StudentCourseUnitEnrollment | None = None,
    course_unit: CourseUnit | None = None,
    academic_level: AcademicLevel | None = None,
    academic_level_id: int | None = None,
) -> AssessmentPolicy | None:
    """
    Level-specific policy first, then global default (academic_level unset).
    """
    level = academic_level
    if level is None and academic_level_id is not None:
        level = AcademicLevel.objects.filter(pk=academic_level_id).first()
    if level is None and enrollment is not None:
        level = academic_level_for_enrollment(enrollment)
    if level is None and course_unit is not None:
        level = academic_level_for_course_unit(course_unit)

    if level is not None:
        policy = AssessmentPolicy.objects.filter(
            is_active=True, academic_level=level
        ).first()
        if policy:
            return policy

    return AssessmentPolicy.get_active_default()

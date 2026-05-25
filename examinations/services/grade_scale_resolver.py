"""Resolve which GradeScale applies for a course or enrollment."""
from __future__ import annotations

from admissions.models import AcademicLevel, AdmittedStudent
from Programs.models import CourseUnit, StudentCourseUnitEnrollment

from ..models import GradeScale
from .policy_resolver import (
    academic_level_for_course_unit,
    academic_level_for_enrollment,
)


def academic_level_for_student(student: AdmittedStudent) -> AcademicLevel | None:
    try:
        enrollment = student.programme_enrollment
    except Exception:
        return None
    if enrollment and enrollment.program_id:
        return enrollment.program.academic_level
    return None


def resolve_grade_scale(
    *,
    enrollment: StudentCourseUnitEnrollment | None = None,
    course_unit: CourseUnit | None = None,
    student: AdmittedStudent | None = None,
    academic_level: AcademicLevel | None = None,
    academic_level_id: int | None = None,
) -> GradeScale | None:
    level = academic_level
    if level is None and academic_level_id is not None:
        level = AcademicLevel.objects.filter(pk=academic_level_id).first()
    if level is None and enrollment is not None:
        level = academic_level_for_enrollment(enrollment)
    if level is None and course_unit is not None:
        level = academic_level_for_course_unit(course_unit)
    if level is None and student is not None:
        level = academic_level_for_student(student)

    if level is not None:
        scale = GradeScale.get_for_academic_level(level)
        if scale:
            return scale

    return GradeScale.get_active_default()

"""Guards for deleting course units / removing enrollments when marks exist."""
from __future__ import annotations

from django.db.models import Q


def enrollment_has_entered_marks(enrollment) -> bool:
    """True when CA/exam/final, grade, or verified/published result exists."""
    try:
        result = enrollment.course_result
    except Exception:
        return False
    if result is None:
        return False
    if (
        result.ca_mark is not None
        or result.exam_mark is not None
        or result.final_mark is not None
    ):
        return True
    if (result.grade_letter or "").strip():
        return True
    if result.grade_point is not None:
        return True
    if (result.paper_outcome or "").strip():
        return True
    from examinations.models import CourseUnitResult

    return result.status in (
        CourseUnitResult.STATUS_VERIFIED,
        CourseUnitResult.STATUS_PUBLISHED,
    )


def course_unit_has_entered_marks(course_unit) -> bool:
    """True when any enrollment on this offering has marks entered."""
    from examinations.models import CourseUnitResult

    return (
        CourseUnitResult.objects.filter(enrollment__course_unit=course_unit)
        .filter(
            Q(ca_mark__isnull=False)
            | Q(exam_mark__isnull=False)
            | Q(final_mark__isnull=False)
            | Q(grade_point__isnull=False)
            | ~Q(grade_letter="")
            | ~Q(paper_outcome="")
            | Q(
                status__in=(
                    CourseUnitResult.STATUS_VERIFIED,
                    CourseUnitResult.STATUS_PUBLISHED,
                )
            )
        )
        .exists()
    )


def course_unit_registered_enrollment_count(course_unit) -> int:
    return course_unit.student_enrollments.filter(
        registration_date__isnull=False
    ).count()

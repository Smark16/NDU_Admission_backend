"""Block another sitting once a course has already been retaken three times.

ARMS hides the course (IsRetaken3X) after three extra sittings. The first
attempt stays a normal enrollment. Each later sitting is a retake or a
missed-paper enrollment on a new offering of the same course code.
"""
from __future__ import annotations

from Programs.models import StudentCourseUnitEnrollment

MAX_EXTRA_SITTINGS = 3


def extra_sitting_count(student, course_code: str) -> int:
    code = (course_code or "").strip()
    if not student or not code:
        return 0
    return StudentCourseUnitEnrollment.objects.filter(
        student=student,
        course_unit__code__iexact=code,
        registration_kind__in=(
            StudentCourseUnitEnrollment.KIND_RETAKE,
            StudentCourseUnitEnrollment.KIND_MISSED,
        ),
    ).count()


def retake_limit_reached(student, course_code: str) -> bool:
    return extra_sitting_count(student, course_code) >= MAX_EXTRA_SITTINGS


def retake_limit_message(course_code: str) -> str:
    code = (course_code or "This course").strip()
    return (
        f"{code} has already been retaken three times "
        "and cannot be registered again."
    )

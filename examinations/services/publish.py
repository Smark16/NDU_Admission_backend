"""Publish / verify helpers."""
from django.utils import timezone

from Programs.models import StudentCourseUnitEnrollment

from ..models import CourseUnitResult


def sync_enrollment_from_result(result: CourseUnitResult) -> None:
    enr: StudentCourseUnitEnrollment = result.enrollment
    if result.grade_letter:
        enr.grade = result.grade_letter
    if result.is_pass is False:
        enr.status = "failed"
    elif result.is_pass is True:
        enr.status = "completed"
    enr.save(update_fields=["grade", "status", "updated_at"])


def publish_result(result: CourseUnitResult, *, user, grade_scale=None) -> None:
    result.recompute(grade_scale=grade_scale)
    result.status = CourseUnitResult.STATUS_PUBLISHED
    result.published_at = timezone.now()
    result.published_by = user
    result.edit_unlocked = False
    result.save()
    sync_enrollment_from_result(result)


def verify_result(result: CourseUnitResult, *, user, grade_scale=None) -> None:
    result.recompute(grade_scale=grade_scale)
    result.status = CourseUnitResult.STATUS_VERIFIED
    result.verified_at = timezone.now()
    result.verified_by = user
    result.save()

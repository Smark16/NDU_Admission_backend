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


def unpublish_result(result: CourseUnitResult, *, user=None) -> None:
    """
    Hide result from students again (back to verified / submitted).
    Keeps marks; enrollment returns to enrolled so the row stays on Marks.
    """
    result.status = CourseUnitResult.STATUS_VERIFIED
    result.published_at = None
    result.published_by = None
    result.edit_unlocked = False
    if result.verified_at is None:
        result.verified_at = timezone.now()
        if user is not None:
            result.verified_by = user
    result.save(
        update_fields=[
            "status",
            "published_at",
            "published_by",
            "edit_unlocked",
            "verified_at",
            "verified_by",
            "updated_at",
        ]
    )
    enr = result.enrollment
    if enr.status in ("completed", "failed"):
        enr.status = "enrolled"
        enr.save(update_fields=["status", "updated_at"])


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

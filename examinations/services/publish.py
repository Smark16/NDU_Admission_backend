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


def publish_result(result: CourseUnitResult, *, user, grade_scale=None, override=False) -> None:
    """Publish -- the AR's final action. Requires Dean approval unless ``override``
    (Super Admin direct publish, e.g. for a correction)."""
    if not override and result.dean_status != CourseUnitResult.REVIEW_APPROVED:
        raise PermissionError(
            "Cannot publish: Dean approval is still pending for this result."
        )
    result.recompute(grade_scale=grade_scale)
    result.status = CourseUnitResult.STATUS_PUBLISHED
    result.published_at = timezone.now()
    result.published_by = user
    result.edit_unlocked = False
    result.save()
    sync_enrollment_from_result(result)


def verify_result(result: CourseUnitResult, *, user, grade_scale=None) -> None:
    """Lecturer's submit action. Restarts the HOD/Dean approval chain -- relevant
    when re-submitting after a rejection or a post-publish edit."""
    result.recompute(grade_scale=grade_scale)
    result.status = CourseUnitResult.STATUS_VERIFIED
    result.verified_at = timezone.now()
    result.verified_by = user
    result.submitted_by = user
    result.submitted_at = timezone.now()
    result.hod_status = CourseUnitResult.REVIEW_PENDING
    result.hod_reviewed_by = None
    result.hod_reviewed_at = None
    result.dean_status = CourseUnitResult.REVIEW_PENDING
    result.dean_reviewed_by = None
    result.dean_reviewed_at = None
    result.save()


def hod_review_result(result: CourseUnitResult, *, user, decision: str, notes: str = "") -> None:
    result.hod_status = decision
    result.hod_reviewed_by = user
    result.hod_reviewed_at = timezone.now()
    result.hod_notes = notes
    if decision == CourseUnitResult.REVIEW_REJECTED:
        # Kick back to draft so the lecturer can fix and resubmit.
        result.status = CourseUnitResult.STATUS_DRAFT
        result.dean_status = CourseUnitResult.REVIEW_PENDING
    result.save(
        update_fields=[
            "hod_status", "hod_reviewed_by", "hod_reviewed_at", "hod_notes",
            "status", "dean_status", "updated_at",
        ]
    )


def dean_review_result(result: CourseUnitResult, *, user, decision: str, notes: str = "") -> None:
    result.dean_status = decision
    result.dean_reviewed_by = user
    result.dean_reviewed_at = timezone.now()
    result.dean_notes = notes
    if decision == CourseUnitResult.REVIEW_REJECTED:
        result.status = CourseUnitResult.STATUS_DRAFT
        result.hod_status = CourseUnitResult.REVIEW_PENDING
    result.save(
        update_fields=[
            "dean_status", "dean_reviewed_by", "dean_reviewed_at", "dean_notes",
            "status", "hod_status", "updated_at",
        ]
    )

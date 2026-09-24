"""Marks approval chain: HOD review (stage 1) and Dean review (stage 2),
sitting between the lecturer's Submit action and the AR's final Publish.
"""
from django.db import transaction
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.super_admin import user_is_super_admin
from admissions.faculty_scope import user_can_access_course_unit
from Programs.models import CourseUnit

from .models import CourseUnitResult
from .permissions import _has
from .services.publish import dean_review_result, hod_review_result
from .views import _get_course_unit_or_404

VALID_DECISIONS = {CourseUnitResult.REVIEW_APPROVED, CourseUnitResult.REVIEW_REJECTED}


def _parse_decision(request):
    decision = (request.data.get("decision") or "").strip().lower()
    if decision not in VALID_DECISIONS:
        return None, Response(
            {"detail": f"decision must be one of {sorted(VALID_DECISIONS)}."}, status=400,
        )
    return decision, None


def _parse_enrollment_ids(request):
    raw_ids = request.data.get("enrollment_ids") if hasattr(request.data, "get") else None
    if raw_ids is None:
        return None, None
    if not isinstance(raw_ids, list) or not raw_ids:
        return None, Response(
            {"detail": "enrollment_ids must be a non-empty list of enrollment ids."}, status=400,
        )
    try:
        return [int(x) for x in raw_ids], None
    except (TypeError, ValueError):
        return None, Response({"detail": "enrollment_ids must contain integers."}, status=400)


class HODReviewMarksView(APIView):
    """Stage 1: HOD approves or rejects a course's submitted (verified) marks."""

    permission_classes = [IsAuthenticated]

    def post(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        if not (
            user_is_super_admin(request.user)
            or _has(request.user, "examinations.review_marks_hod")
        ):
            return Response(
                {"detail": "You do not have permission to review marks at the HOD stage."},
                status=403,
            )
        if not user_can_access_course_unit(request.user, course_unit):
            return Response(
                {"detail": "This course unit is outside your assigned faculty."}, status=403,
            )

        decision, error = _parse_decision(request)
        if error:
            return error
        enrollment_ids, error = _parse_enrollment_ids(request)
        if error:
            return error
        notes = (request.data.get("notes") or "")[:255]

        qs = CourseUnitResult.objects.filter(
            enrollment__course_unit_id=course_unit_id,
            status=CourseUnitResult.STATUS_VERIFIED,
        )
        if enrollment_ids is not None:
            qs = qs.filter(enrollment_id__in=enrollment_ids)

        reviewed = 0
        with transaction.atomic():
            for result in qs:
                hod_review_result(result, user=request.user, decision=decision, notes=notes)
                reviewed += 1

        return Response(
            {
                "course_unit_id": course_unit_id,
                "decision": decision,
                "reviewed_count": reviewed,
                "message": f"HOD {decision} {reviewed} result(s).",
            }
        )


class DeanReviewMarksView(APIView):
    """Stage 2: Dean approves or rejects HOD-approved marks."""

    permission_classes = [IsAuthenticated]

    def post(self, request, course_unit_id):
        try:
            course_unit = _get_course_unit_or_404(course_unit_id)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Course unit not found."}, status=404)

        if not (
            user_is_super_admin(request.user)
            or _has(request.user, "examinations.review_marks_dean")
        ):
            return Response(
                {"detail": "You do not have permission to review marks at the Dean stage."},
                status=403,
            )
        if not user_can_access_course_unit(request.user, course_unit):
            return Response(
                {"detail": "This course unit is outside your assigned faculty."}, status=403,
            )

        decision, error = _parse_decision(request)
        if error:
            return error
        enrollment_ids, error = _parse_enrollment_ids(request)
        if error:
            return error
        notes = (request.data.get("notes") or "")[:255]

        qs = CourseUnitResult.objects.filter(
            enrollment__course_unit_id=course_unit_id,
            status=CourseUnitResult.STATUS_VERIFIED,
            hod_status=CourseUnitResult.REVIEW_APPROVED,
        )
        if enrollment_ids is not None:
            qs = qs.filter(enrollment_id__in=enrollment_ids)

        reviewed = 0
        skipped_not_hod_approved = CourseUnitResult.objects.filter(
            enrollment__course_unit_id=course_unit_id,
            status=CourseUnitResult.STATUS_VERIFIED,
        ).exclude(hod_status=CourseUnitResult.REVIEW_APPROVED).count()
        with transaction.atomic():
            for result in qs:
                dean_review_result(result, user=request.user, decision=decision, notes=notes)
                reviewed += 1

        message = f"Dean {decision} {reviewed} result(s)."
        if skipped_not_hod_approved:
            message += (
                f" {skipped_not_hod_approved} result(s) skipped -- not yet HOD-approved."
            )
        return Response(
            {
                "course_unit_id": course_unit_id,
                "decision": decision,
                "reviewed_count": reviewed,
                "skipped_not_hod_approved": skipped_not_hod_approved,
                "message": message,
            }
        )

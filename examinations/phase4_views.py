"""Phase 4: post-publish grade changes, unlock, appeals."""
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Programs.models import CourseUnit

from .models import CourseUnitResult, ResultChangeRequest
from .permissions import (
    CanApproveResultChanges,
    CanEnterMarksOrAssignedLecturer,
    user_can_manage_course_marks,
)
from .serializers import ResultChangeRequestSerializer
from .services.publish import publish_result, sync_enrollment_from_result


def _apply_approved_change(change: ResultChangeRequest, *, reviewer) -> None:
    result = change.result
    if change.new_ca_mark is not None:
        result.ca_mark = change.new_ca_mark
    if change.new_exam_mark is not None:
        result.exam_mark = change.new_exam_mark
    result.recompute()
    result.status = CourseUnitResult.STATUS_PUBLISHED
    result.edit_unlocked = False
    result.save()
    sync_enrollment_from_result(result)
    change.status = ResultChangeRequest.STATUS_APPROVED
    change.reviewed_by = reviewer
    change.reviewed_at = timezone.now()
    change.save()


class ResultChangeRequestListView(APIView):
    permission_classes = [IsAuthenticated, CanApproveResultChanges]

    def get(self, request):
        status_filter = request.query_params.get("status", "pending")
        course_unit_id = request.query_params.get("course_unit_id")
        qs = ResultChangeRequest.objects.select_related(
            "result",
            "result__enrollment",
            "result__enrollment__student",
            "result__enrollment__course_unit",
            "requested_by",
        ).order_by("-requested_at")
        if status_filter and status_filter != "all":
            qs = qs.filter(status=status_filter)
        if course_unit_id:
            qs = qs.filter(result__enrollment__course_unit_id=course_unit_id)
        return Response(
            {
                "requests": ResultChangeRequestSerializer(qs[:200], many=True).data,
                "count": qs.count(),
            }
        )


class CreateResultChangeRequestView(APIView):
    """Request a change to a published result (lecturer or staff)."""

    permission_classes = [IsAuthenticated, CanEnterMarksOrAssignedLecturer]

    def post(self, request, result_id):
        result = get_object_or_404(
            CourseUnitResult.objects.select_related("enrollment", "enrollment__course_unit"),
            pk=result_id,
        )
        course_unit = result.enrollment.course_unit
        if not user_can_manage_course_marks(request.user, course_unit):
            return Response({"detail": "Forbidden."}, status=403)

        if result.status != CourseUnitResult.STATUS_PUBLISHED:
            return Response(
                {"detail": "Change requests apply to published results only."},
                status=400,
            )

        if ResultChangeRequest.objects.filter(
            result=result, status=ResultChangeRequest.STATUS_PENDING
        ).exists():
            return Response({"detail": "A pending request already exists."}, status=400)

        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"detail": "reason is required."}, status=400)

        change = ResultChangeRequest.objects.create(
            result=result,
            requested_by=request.user,
            reason=reason,
            old_ca_mark=result.ca_mark,
            old_exam_mark=result.exam_mark,
            old_final_mark=result.final_mark,
            old_grade_letter=result.grade_letter,
            new_ca_mark=request.data.get("new_ca_mark"),
            new_exam_mark=request.data.get("new_exam_mark"),
        )
        return Response(ResultChangeRequestSerializer(change).data, status=201)


class ResultChangeRequestDetailView(APIView):
    permission_classes = [IsAuthenticated, CanApproveResultChanges]

    def patch(self, request, request_id):
        change = get_object_or_404(
            ResultChangeRequest.objects.select_related("result"),
            pk=request_id,
        )
        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"detail": "action must be approve or reject."}, status=400)

        if change.status != ResultChangeRequest.STATUS_PENDING:
            return Response({"detail": "Request is not pending."}, status=400)

        change.review_notes = (request.data.get("review_notes") or "").strip()

        if action == "reject":
            change.status = ResultChangeRequest.STATUS_REJECTED
            change.reviewed_by = request.user
            change.reviewed_at = timezone.now()
            change.save()
            return Response(ResultChangeRequestSerializer(change).data)

        if request.data.get("new_ca_mark") is not None:
            change.new_ca_mark = request.data["new_ca_mark"]
        if request.data.get("new_exam_mark") is not None:
            change.new_exam_mark = request.data["new_exam_mark"]
        change.save(update_fields=["new_ca_mark", "new_exam_mark"])

        if change.new_ca_mark is None and change.new_exam_mark is None:
            return Response(
                {"detail": "Set new_ca_mark and/or new_exam_mark before approving."},
                status=400,
            )

        with transaction.atomic():
            _apply_approved_change(change, reviewer=request.user)

        return Response(ResultChangeRequestSerializer(change).data)


class UnlockPublishedResultView(APIView):
    """Temporarily unlock a published result for direct edit (re-publish required)."""

    permission_classes = [IsAuthenticated, CanApproveResultChanges]

    def post(self, request, result_id):
        result = get_object_or_404(CourseUnitResult, pk=result_id)
        if result.status != CourseUnitResult.STATUS_PUBLISHED:
            return Response({"detail": "Only published results can be unlocked."}, status=400)

        result.edit_unlocked = True
        result.status = CourseUnitResult.STATUS_VERIFIED
        result.save(update_fields=["edit_unlocked", "status", "updated_at"])
        return Response(
            {
                "detail": "Result unlocked for editing. Save marks then publish again.",
                "result_id": result.id,
                "status": result.status,
            }
        )

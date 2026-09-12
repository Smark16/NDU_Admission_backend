from django.db import transaction
from django.db.models.deletion import ProtectedError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.super_admin import user_is_super_admin

from .course_api_views import serialize_course_unit
from .course_unit_marks_guards import (
    course_unit_has_entered_marks,
    course_unit_registered_enrollment_count,
)
from .models import CourseUnit
from .permissions import ProgramSchedulingAPIPermission


class DeleteCourseUnitView(APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def delete(self, request, pk):
        try:
            cu = CourseUnit.objects.get(pk=pk)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)

        if course_unit_has_entered_marks(cu):
            return Response(
                {
                    "detail": (
                        "This course unit cannot be deleted because marks have already "
                        "been entered for one or more students."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        registered_n = course_unit_registered_enrollment_count(cu)
        enrollment_n = cu.student_enrollments.count()
        is_sa = user_is_super_admin(request.user)

        # Non–Super Admin: block if anyone is enrolled/registered.
        if enrollment_n and not is_sa:
            return Response(
                {
                    "detail": (
                        f"Cannot delete: {enrollment_n} student(s) are enrolled on this "
                        "course unit. Remove enrollments first, or ask a Super Admin "
                        "(allowed only when no marks have been entered)."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Super Admin may delete even when students are registered, if no marks.
        try:
            with transaction.atomic():
                code = cu.code
                cu.delete()
        except ProtectedError:
            return Response(
                {
                    "detail": (
                        "Cannot delete this course unit because related records still "
                        "depend on it. Contact support if marks were cleared but delete still fails."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        msg = f"Course unit {code} deleted."
        if is_sa and registered_n:
            msg += f" Removed {registered_n} registered enrollment(s) (no marks)."
        return Response({"detail": msg}, status=status.HTTP_200_OK)


class PatchCourseUnitStatusView(APIView):
    permission_classes = [ProgramSchedulingAPIPermission]

    def patch(self, request, pk):
        try:
            cu = CourseUnit.objects.get(pk=pk)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if "is_active" in request.data:
            cu.is_active = bool(request.data["is_active"])
            cu.save()
        return Response(serialize_course_unit(cu))

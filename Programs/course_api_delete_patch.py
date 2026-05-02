from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .course_api_views import serialize_course_unit
from .models import CourseUnit


class DeleteCourseUnitView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            cu = CourseUnit.objects.get(pk=pk)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        cu.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class PatchCourseUnitStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, pk):
        try:
            cu = CourseUnit.objects.get(pk=pk)
        except CourseUnit.DoesNotExist:
            return Response({"detail": "Not found"}, status=status.HTTP_404_NOT_FOUND)
        if "is_active" in request.data:
            cu.is_active = bool(request.data["is_active"])
            cu.save()
        return Response(serialize_course_unit(cu))

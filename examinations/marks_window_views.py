from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import MarksEntryWindow
from .permissions import CanManageMarksWindows
from .serializers import MarksEntryWindowSerializer


class MarksEntryWindowListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageMarksWindows]

    def get(self, request):
        qs = MarksEntryWindow.objects.select_related(
            "program_batch",
            "semester",
            "course_unit",
        ).order_by("-is_active", "program_batch__name", "semester__order", "course_unit__code")

        program_batch_id = request.query_params.get("program_batch_id")
        semester_id = request.query_params.get("semester_id")
        course_unit_id = request.query_params.get("course_unit_id")
        active = request.query_params.get("active")

        if program_batch_id:
            qs = qs.filter(program_batch_id=program_batch_id)
        if semester_id:
            qs = qs.filter(semester_id=semester_id)
        if course_unit_id:
            qs = qs.filter(course_unit_id=course_unit_id)
        if active and active.lower() in ("1", "true", "yes"):
            qs = qs.filter(is_active=True)

        return Response({"windows": MarksEntryWindowSerializer(qs[:200], many=True).data})

    def post(self, request):
        serializer = MarksEntryWindowSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        window = serializer.save(created_by=request.user)
        return Response(MarksEntryWindowSerializer(window).data, status=201)


class MarksEntryWindowDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageMarksWindows]

    def patch(self, request, window_id):
        window = get_object_or_404(MarksEntryWindow, pk=window_id)
        serializer = MarksEntryWindowSerializer(window, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        updated = serializer.save()
        return Response(MarksEntryWindowSerializer(updated).data)

    def delete(self, request, window_id):
        window = get_object_or_404(MarksEntryWindow, pk=window_id)
        window.is_active = False
        window.closed_by = request.user
        window.closed_at = timezone.now()
        window.save(update_fields=["is_active", "closed_by", "closed_at", "updated_at"])
        return Response(MarksEntryWindowSerializer(window).data)


class MarksEntryWindowOpenView(APIView):
    permission_classes = [IsAuthenticated, CanManageMarksWindows]

    def post(self, request, window_id):
        window = get_object_or_404(MarksEntryWindow, pk=window_id)
        now = timezone.now()
        window.is_active = True
        if window.opens_at is None or window.opens_at > now:
            window.opens_at = now
        if window.closes_at and window.closes_at <= now:
            window.closes_at = None
        window.closed_by = None
        window.closed_at = None
        window.save(
            update_fields=[
                "is_active",
                "opens_at",
                "closes_at",
                "closed_by",
                "closed_at",
                "updated_at",
            ]
        )
        return Response(MarksEntryWindowSerializer(window).data)


class MarksEntryWindowCloseView(APIView):
    permission_classes = [IsAuthenticated, CanManageMarksWindows]

    def post(self, request, window_id):
        window = get_object_or_404(MarksEntryWindow, pk=window_id)
        now = timezone.now()
        window.is_active = True
        window.closes_at = now
        window.closed_by = request.user
        window.closed_at = now
        window.save(
            update_fields=[
                "is_active",
                "closes_at",
                "closed_by",
                "closed_at",
                "updated_at",
            ]
        )
        return Response(MarksEntryWindowSerializer(window).data)

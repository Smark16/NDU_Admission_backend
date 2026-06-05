from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AcademicLevel

from .models import GradeScale
from .permissions import CanManageAssessmentPolicies
from .serializers import (
    GradeScaleDetailSerializer,
    GradeScaleListSerializer,
    GradeScaleWriteSerializer,
    _deactivate_active_for_level,
)
from .services.grade_scale_resolver import resolve_grade_scale


class ActiveGradeScaleView(APIView):
    """Active grading scheme (read-only for marks entry and transcripts)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from Programs.models import CourseUnit

        course_unit_id = request.query_params.get("course_unit_id")
        academic_level_id = request.query_params.get("academic_level_id")
        course_unit = None
        if course_unit_id:
            course_unit = (
                CourseUnit.objects.select_related("program_batch__program__academic_level")
                .filter(pk=course_unit_id, is_active=True)
                .first()
            )
            if not course_unit:
                return Response({"detail": "Course unit not found."}, status=404)
        level = None
        if academic_level_id and not course_unit:
            level = AcademicLevel.objects.filter(pk=academic_level_id).first()
            if not level:
                return Response({"detail": "Academic level not found."}, status=404)

        scale = resolve_grade_scale(course_unit=course_unit, academic_level=level)
        if not scale:
            return Response({"detail": "No grading scheme configured."}, status=404)
        return Response(GradeScaleDetailSerializer(scale).data)


class GradeScaleListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def get(self, request):
        scales = GradeScale.objects.prefetch_related("bands").order_by("-is_active", "name")
        return Response(GradeScaleListSerializer(scales, many=True).data)

    def post(self, request):
        serializer = GradeScaleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            scale = serializer.save()
        scale = GradeScale.objects.prefetch_related("bands").get(pk=scale.pk)
        return Response(
            GradeScaleDetailSerializer(scale).data,
            status=status.HTTP_201_CREATED,
        )


class GradeScaleDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def get(self, request, scale_id):
        scale = get_object_or_404(GradeScale.objects.prefetch_related("bands"), pk=scale_id)
        return Response(GradeScaleDetailSerializer(scale).data)

    def patch(self, request, scale_id):
        scale = get_object_or_404(GradeScale, pk=scale_id)
        serializer = GradeScaleWriteSerializer(scale, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            scale = serializer.save()
        scale = GradeScale.objects.prefetch_related("bands").get(pk=scale.pk)
        return Response(GradeScaleDetailSerializer(scale).data)

    def put(self, request, scale_id):
        scale = get_object_or_404(GradeScale, pk=scale_id)
        serializer = GradeScaleWriteSerializer(scale, data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            scale = serializer.save()
        scale = GradeScale.objects.prefetch_related("bands").get(pk=scale.pk)
        return Response(GradeScaleDetailSerializer(scale).data)

    def delete(self, request, scale_id):
        scale = get_object_or_404(GradeScale, pk=scale_id)
        if scale.is_active:
            return Response(
                {
                    "detail": (
                        "Cannot delete the active grading scheme for this scope. "
                        "Activate another scheme first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        scale.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class GradeScaleActivateView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def post(self, request, scale_id):
        scale = get_object_or_404(GradeScale.objects.prefetch_related("bands"), pk=scale_id)
        if not scale.bands.exists():
            return Response(
                {"detail": "Add at least one grade band before activating this scheme."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        level_pk = scale.academic_level_id
        with transaction.atomic():
            _deactivate_active_for_level(GradeScale, level_pk, exclude_pk=scale.pk)
            scale.is_active = True
            scale.save(update_fields=["is_active"])
        return Response(GradeScaleDetailSerializer(scale).data)

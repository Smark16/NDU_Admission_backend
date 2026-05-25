from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AcademicLevel
from Programs.models import CourseUnit

from .models import AwardClassificationScheme
from .permissions import CanManageAssessmentPolicies
from .serializers import (
    AwardSchemeDetailSerializer,
    AwardSchemeListSerializer,
    AwardSchemeWriteSerializer,
    _deactivate_active_for_level,
)
from .services.award_classification import resolve_award_class, resolve_award_classification_scheme


class ActiveAwardSchemeView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        academic_level_id = request.query_params.get("academic_level_id")
        level = None
        if academic_level_id:
            level = AcademicLevel.objects.filter(pk=academic_level_id).first()
            if not level:
                return Response({"detail": "Academic level not found."}, status=404)

        scheme = resolve_award_classification_scheme(academic_level=level)
        if not scheme:
            return Response({"detail": "No award classification scheme configured."}, status=404)
        return Response(AwardSchemeDetailSerializer(scheme).data)


class AwardSchemeListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def get(self, request):
        schemes = AwardClassificationScheme.objects.prefetch_related("bands").order_by(
            "-is_active", "name"
        )
        return Response(AwardSchemeListSerializer(schemes, many=True).data)

    def post(self, request):
        serializer = AwardSchemeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            scheme = serializer.save()
        scheme = AwardClassificationScheme.objects.prefetch_related("bands").get(pk=scheme.pk)
        return Response(
            AwardSchemeDetailSerializer(scheme).data,
            status=status.HTTP_201_CREATED,
        )


class AwardSchemeDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def get(self, request, scheme_id):
        scheme = get_object_or_404(
            AwardClassificationScheme.objects.prefetch_related("bands"), pk=scheme_id
        )
        return Response(AwardSchemeDetailSerializer(scheme).data)

    def patch(self, request, scheme_id):
        scheme = get_object_or_404(AwardClassificationScheme, pk=scheme_id)
        serializer = AwardSchemeWriteSerializer(scheme, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            scheme = serializer.save()
        scheme = AwardClassificationScheme.objects.prefetch_related("bands").get(pk=scheme.pk)
        return Response(AwardSchemeDetailSerializer(scheme).data)

    def put(self, request, scheme_id):
        scheme = get_object_or_404(AwardClassificationScheme, pk=scheme_id)
        serializer = AwardSchemeWriteSerializer(scheme, data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            scheme = serializer.save()
        scheme = AwardClassificationScheme.objects.prefetch_related("bands").get(pk=scheme.pk)
        return Response(AwardSchemeDetailSerializer(scheme).data)

    def delete(self, request, scheme_id):
        scheme = get_object_or_404(AwardClassificationScheme, pk=scheme_id)
        if scheme.is_active:
            return Response(
                {
                    "detail": (
                        "Cannot delete the active award scheme for this scope. "
                        "Activate another scheme first."
                    )
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        scheme.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class AwardSchemeActivateView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def post(self, request, scheme_id):
        scheme = get_object_or_404(
            AwardClassificationScheme.objects.prefetch_related("bands"), pk=scheme_id
        )
        if not scheme.bands.exists():
            return Response(
                {"detail": "Add at least one award class before activating."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        level_pk = scheme.academic_level_id
        with transaction.atomic():
            _deactivate_active_for_level(
                AwardClassificationScheme, level_pk, exclude_pk=scheme.pk
            )
            scheme.is_active = True
            scheme.save(update_fields=["is_active"])
        return Response(AwardSchemeDetailSerializer(scheme).data)


class AwardClassPreviewView(APIView):
    """Preview award class for a CGPA and optional academic level."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        cgpa = request.query_params.get("cgpa")
        academic_level_id = request.query_params.get("academic_level_id")
        if cgpa is None:
            return Response({"detail": "cgpa query parameter is required."}, status=400)
        level = None
        if academic_level_id:
            level = AcademicLevel.objects.filter(pk=academic_level_id).first()
        title = resolve_award_class(cgpa, academic_level=level, academic_level_id=academic_level_id)
        return Response({"cgpa": cgpa, "award_class": title})

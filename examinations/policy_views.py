from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from admissions.models import AcademicLevel
from Programs.models import CourseUnit

from .models import AssessmentPolicy
from .permissions import CanManageAssessmentPolicies
from .serializers import AssessmentPolicySerializer, AssessmentPolicyWriteSerializer
from .services.policy_resolver import resolve_assessment_policy


class ActivePolicyView(APIView):
    """Active policy for a course unit, academic level, or global default."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        course_unit_id = request.query_params.get("course_unit_id")
        academic_level_id = request.query_params.get("academic_level_id")

        course_unit = None
        if course_unit_id:
            course_unit = (
                CourseUnit.objects.select_related(
                    "program_batch__program__academic_level"
                )
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

        policy = resolve_assessment_policy(
            course_unit=course_unit,
            academic_level=level,
        )
        if not policy:
            return Response({"detail": "No assessment policy configured."}, status=404)

        level_name = None
        if course_unit and course_unit.program_batch_id:
            prog = course_unit.program_batch.program
            if prog.academic_level_id:
                level_name = prog.academic_level.name
        elif level:
            level_name = level.name
        elif policy.academic_level_id:
            level_name = policy.academic_level.name

        data = AssessmentPolicySerializer(policy).data
        data["academic_level_name"] = level_name
        data["scope"] = (
            "academic_level"
            if policy.academic_level_id
            else ("course" if level_name and not policy.academic_level_id else "global")
        )
        return Response(data)


class AssessmentPolicyListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def get(self, request):
        policies = AssessmentPolicy.objects.select_related("academic_level").order_by(
            "academic_level__name", "name"
        )
        return Response(AssessmentPolicySerializer(policies, many=True).data)

    def post(self, request):
        serializer = AssessmentPolicyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        return Response(
            AssessmentPolicySerializer(policy).data,
            status=status.HTTP_201_CREATED,
        )


class AssessmentPolicyDetailView(APIView):
    permission_classes = [IsAuthenticated, CanManageAssessmentPolicies]

    def get(self, request, policy_id):
        policy = get_object_or_404(
            AssessmentPolicy.objects.select_related("academic_level"),
            pk=policy_id,
        )
        return Response(AssessmentPolicySerializer(policy).data)

    def patch(self, request, policy_id):
        policy = get_object_or_404(AssessmentPolicy, pk=policy_id)
        serializer = AssessmentPolicyWriteSerializer(
            policy, data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        return Response(AssessmentPolicySerializer(policy).data)

    def delete(self, request, policy_id):
        policy = get_object_or_404(AssessmentPolicy, pk=policy_id)
        if policy.is_default:
            return Response(
                {"detail": "Cannot delete the global default policy. Deactivate or replace it first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if policy.results.exists():
            return Response(
                {"detail": "Policy is linked to published results and cannot be deleted."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        policy.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

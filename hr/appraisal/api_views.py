from django.utils import timezone
from django.db.models import Avg
from django.http import HttpResponse
from datetime import timedelta
import csv
import io
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated, DjangoModelPermissions
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Campus
from hr.staff.utils.profile_sync import resolve_staff_profile_for_user

from .models import Appraisal, AppraisalCycle, AppraisalObjective, BehavioralCompetency, PerformanceFactor, PerformanceImprovementPlan, StrategicObjective
from .serializers import (
    AppraisalCreateSerializer,
    AppraisalCycleCreateSerializer,
    AppraisalCycleListSerializer,
    AppraisalDetailSerializer,
    AppraisalListSerializer,
    AppraisalStatusSerializer,
    PerformanceImprovementPlanSerializer,
    StrategicObjectiveSerializer,
)
from .objective_utils import ensure_appraisal_assessment_scaffold


def _get_staff_for_user(user):
    return resolve_staff_profile_for_user(user)


def _user_can_manage_pips(user):
    return (
        user.has_perm("staff.view_pips")
        or user.has_perm("appraisal.view_performanceimprovementplan")
        or user.has_perm("appraisal.add_performanceimprovementplan")
        or user.has_perm("appraisal.change_performanceimprovementplan")
    )


STAFF_PROFILE_LINK_ERROR = (
    "Staff profile not linked to your login. "
    "Use the same university email in Staff directory, or ask HR to link your ERP account."
)


class AppraisalCycleListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AppraisalCycleListSerializer
    queryset = AppraisalCycle.objects.select_related("campus").order_by("-academic_year")

    def list(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.view_appraisalcycle"):
            return Response({"detail": "You do not have permission to view appraisal cycles."}, status=403)
        return super().list(request, *args, **kwargs)


class AppraisalCycleCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AppraisalCycleCreateSerializer
    queryset = AppraisalCycle.objects.all()

    def create(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.add_appraisalcycle"):
            return Response({"detail": "You do not have permission to create cycles."}, status=403)
        return super().create(request, *args, **kwargs)


class AppraisalCycleDetailView(generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AppraisalCycleCreateSerializer
    queryset = AppraisalCycle.objects.select_related("campus")
    lookup_url_kwarg = "cycle_id"

    def get_serializer_class(self):
        if self.request.method == "GET":
            return AppraisalCycleListSerializer
        return AppraisalCycleCreateSerializer

    def retrieve(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.view_appraisalcycle"):
            return Response({"detail": "You do not have permission to view appraisal cycles."}, status=403)
        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.change_appraisalcycle"):
            return Response({"detail": "You do not have permission to update cycles."}, status=403)
        return super().update(request, *args, **kwargs)

    def partial_update(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)


class AppraisalCycleActivateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, cycle_id):
        if not request.user.has_perm("appraisal.change_appraisalcycle"):
            return Response({"detail": "Permission denied."}, status=403)
        cycle = AppraisalCycle.objects.filter(pk=cycle_id).first()
        if not cycle:
            return Response({"detail": "Cycle not found."}, status=404)
        AppraisalCycle.objects.filter(campus=cycle.campus, is_active=True).update(is_active=False)
        cycle.is_active = True
        cycle.status = "ACTIVE"
        cycle.save(update_fields=["is_active", "status"])
        return Response(AppraisalCycleListSerializer(cycle).data)


class AppraisalListView(generics.ListAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AppraisalListSerializer
    queryset = Appraisal.objects.select_related("staff", "cycle", "supervisor").order_by("-cycle__academic_year")

    def list(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.view_appraisal"):
            return Response({"detail": "You do not have permission to view appraisals."}, status=403)
        qs = self.get_queryset()
        status_filter = request.query_params.get("status")
        cycle_id = request.query_params.get("cycle")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if cycle_id:
            qs = qs.filter(cycle_id=cycle_id)
        return Response(self.get_serializer(qs, many=True).data)


class MyAppraisalsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("appraisal.view_appraisal"):
            return Response({"detail": "You do not have permission to view appraisals."}, status=403)
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": STAFF_PROFILE_LINK_ERROR}, status=400)
        appraisals = Appraisal.objects.filter(staff=staff).select_related("cycle").order_by("-cycle__academic_year")
        return Response(AppraisalListSerializer(appraisals, many=True).data)


class AppraisalCreateView(generics.CreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = AppraisalCreateSerializer
    queryset = Appraisal.objects.all()

    def create(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.add_appraisal"):
            return Response({"detail": "You do not have permission to create appraisals."}, status=403)
        return super().create(request, *args, **kwargs)


class AppraisalStatusUpdateView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, appraisal_id):
        if not request.user.has_perm("appraisal.change_appraisal"):
            return Response({"detail": "Permission denied."}, status=403)
        appraisal = Appraisal.objects.filter(pk=appraisal_id).first()
        if not appraisal:
            return Response({"detail": "Appraisal not found."}, status=404)
        serializer = AppraisalStatusSerializer(appraisal, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        new_status = serializer.validated_data.get("status")
        if new_status == "PUBLISHED":
            appraisal.published_at = timezone.now()
        if new_status == "APPROVED":
            appraisal.hr_approved_at = timezone.now()
        serializer.save()
        appraisal.refresh_from_db()

        # Seed a draft PIP when HR approves an unsatisfactory appraisal.
        if (
            new_status == "APPROVED"
            and appraisal.overall_rating == "UNSATISFACTORY"
            and not PerformanceImprovementPlan.objects.filter(appraisal=appraisal).exists()
        ):
            PerformanceImprovementPlan.objects.create(
                appraisal=appraisal,
                start_date=timezone.now().date(),
                end_date=timezone.now().date() + timedelta(days=90),
                status="DRAFT",
                improvement_areas="Auto-created after unsatisfactory rating. Complete improvement areas and targets.",
                improvement_targets="Define measurable targets before activating this PIP.",
            )

        return Response(AppraisalDetailSerializer(appraisal).data)


class CampusListForAppraisalView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        campuses = Campus.objects.all().order_by("name").values("id", "name", "code")
        return Response(list(campuses))


class AppraisalDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, appraisal_id):
        appraisal = (
            Appraisal.objects.select_related("staff", "cycle", "supervisor")
            .prefetch_related("objectives", "behavioral_competencies", "performance_factors")
            .filter(pk=appraisal_id)
            .first()
        )
        if not appraisal:
            return Response({"detail": "Appraisal not found."}, status=404)

        staff = _get_staff_for_user(request.user)
        can_view = (
            (staff and appraisal.staff_id == staff.id)
            or (staff and appraisal.supervisor_id == staff.id)
            or request.user.has_perm("appraisal.change_appraisal")
        )
        if not can_view:
            return Response({"detail": "Permission denied."}, status=403)
        return Response(AppraisalDetailSerializer(appraisal).data)


class SelfAssessmentSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, appraisal_id):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": STAFF_PROFILE_LINK_ERROR}, status=400)

        appraisal = Appraisal.objects.filter(pk=appraisal_id, staff=staff).first()
        if not appraisal:
            return Response({"detail": "Appraisal not found."}, status=404)
        if appraisal.status not in ["OBJECTIVES_SET", "SELF_ASSESSMENT"]:
            return Response({"detail": "Objectives must be set before self-assessment."}, status=400)

        objectives = request.data.get("objectives") or []
        for item in objectives:
            obj = AppraisalObjective.objects.filter(pk=item.get("id"), appraisal=appraisal).first()
            if not obj:
                continue
            if item.get("individual_score_percentage") is not None:
                obj.individual_score_percentage = item["individual_score_percentage"]
            if "achievements" in item:
                obj.achievements = item["achievements"] or ""
            obj.save()

        for item in request.data.get("behavioral_competencies") or []:
            comp = BehavioralCompetency.objects.filter(pk=item.get("id"), appraisal=appraisal).first()
            if comp and item.get("self_assessment") is not None:
                comp.self_assessment = int(item["self_assessment"])
                comp.save()

        for item in request.data.get("performance_factors") or []:
            factor = PerformanceFactor.objects.filter(pk=item.get("id"), appraisal=appraisal).first()
            if factor and item.get("self_assessment") is not None:
                factor.self_assessment = int(item["self_assessment"])
                factor.save()

        submit = request.data.get("submit", False)
        if submit:
            appraisal.status = "SELF_COMPLETED"
            appraisal.self_completed_at = timezone.now()
        else:
            appraisal.status = "SELF_ASSESSMENT"
        appraisal.save()

        appraisal.refresh_from_db()
        return Response(AppraisalDetailSerializer(appraisal).data)


class StrategicObjectivesListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        objectives = StrategicObjective.objects.filter(is_active=True).order_by("code")
        return Response(StrategicObjectiveSerializer(objectives, many=True).data)


class SetObjectivesView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, appraisal_id):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": STAFF_PROFILE_LINK_ERROR}, status=400)

        appraisal = (
            Appraisal.objects.filter(pk=appraisal_id, supervisor=staff)
            .prefetch_related("objectives")
            .first()
        )
        if not appraisal:
            return Response({"detail": "Appraisal not found."}, status=404)
        if appraisal.status not in ["DRAFT", "OBJECTIVES_SET"]:
            return Response(
                {"detail": "Objectives can only be edited while appraisal is in Draft or Objectives Set status."},
                status=400,
            )

        delete_ids = request.data.get("delete_ids") or []
        if delete_ids:
            AppraisalObjective.objects.filter(appraisal=appraisal, pk__in=delete_ids).delete()

        for item in request.data.get("objectives") or []:
            title = (item.get("individual_objective") or "").strip()
            strategic_id = item.get("strategic_objective")
            if not title or not strategic_id:
                continue

            values = {
                "strategic_objective_id": strategic_id,
                "individual_objective": title,
                "indicative_tasks": item.get("indicative_tasks") or "",
                "target_percentage": item.get("target_percentage", 95),
                "baseline_percentage": item.get("baseline_percentage", 80),
                "weight": item.get("weight", 5),
            }
            obj_id = item.get("id")
            if obj_id:
                AppraisalObjective.objects.filter(pk=obj_id, appraisal=appraisal).update(**values)
            else:
                AppraisalObjective.objects.create(appraisal=appraisal, **values)

        finalize = bool(request.data.get("finalize"))
        if finalize:
            if not appraisal.objectives.exists():
                return Response({"detail": "Add at least one objective before finalizing."}, status=400)
            ensure_appraisal_assessment_scaffold(appraisal)
            appraisal.status = "OBJECTIVES_SET"
            appraisal.save(update_fields=["status"])

        appraisal = (
            Appraisal.objects.filter(pk=appraisal.pk)
            .prefetch_related("objectives", "behavioral_competencies", "performance_factors")
            .first()
        )
        return Response(AppraisalDetailSerializer(appraisal).data)


class AcknowledgeAppraisalView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, appraisal_id):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": STAFF_PROFILE_LINK_ERROR}, status=400)

        appraisal = Appraisal.objects.filter(pk=appraisal_id, staff=staff).first()
        if not appraisal:
            return Response({"detail": "Appraisal not found."}, status=404)
        if appraisal.status != "PUBLISHED":
            return Response({"detail": "This appraisal is not yet published."}, status=400)

        appraisal.staff_acknowledgment_comment = (request.data.get("comment") or "").strip()
        appraisal.status = "ACKNOWLEDGED"
        appraisal.acknowledged_at = timezone.now()
        appraisal.save()
        return Response(AppraisalDetailSerializer(appraisal).data)


class TeamAppraisalsListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (
            request.user.has_perm("staff.view_team_appraisals")
            or request.user.has_perm("appraisal.change_appraisal")
        ):
            return Response({"detail": "You do not have permission to view team appraisals."}, status=403)
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": STAFF_PROFILE_LINK_ERROR}, status=400)

        appraisals = Appraisal.objects.filter(supervisor=staff).select_related("staff", "cycle").order_by(
            "-cycle__academic_year"
        )
        return Response(AppraisalListSerializer(appraisals, many=True).data)


class SupervisorReviewSubmitView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, appraisal_id):
        staff = _get_staff_for_user(request.user)
        if not staff:
            return Response({"detail": STAFF_PROFILE_LINK_ERROR}, status=400)

        appraisal = (
            Appraisal.objects.filter(pk=appraisal_id, supervisor=staff)
            .prefetch_related("objectives", "behavioral_competencies", "performance_factors")
            .first()
        )
        if not appraisal:
            return Response({"detail": "Appraisal not found."}, status=404)
        if appraisal.status not in ["SELF_COMPLETED", "SUPERVISOR_REVIEW"]:
            return Response({"detail": "Not ready for supervisor review."}, status=400)

        for item in request.data.get("objectives") or []:
            obj = AppraisalObjective.objects.filter(pk=item.get("id"), appraisal=appraisal).first()
            if not obj:
                continue
            if "supervisor_comments" in item:
                obj.supervisor_comments = item["supervisor_comments"] or ""
            if item.get("agreed_score") is not None:
                obj.agreed_score = item["agreed_score"]
            if "action_required" in item:
                obj.action_required = item["action_required"] or ""
            obj.save()

        for item in request.data.get("behavioral_competencies") or []:
            comp = BehavioralCompetency.objects.filter(pk=item.get("id"), appraisal=appraisal).first()
            if not comp:
                continue
            if item.get("supervisor_assessment") is not None:
                comp.supervisor_assessment = int(item["supervisor_assessment"])
            if item.get("agreed_assessment") is not None:
                comp.agreed_assessment = int(item["agreed_assessment"])
            elif comp.supervisor_assessment is not None and comp.agreed_assessment is None:
                comp.agreed_assessment = comp.supervisor_assessment
            comp.save()

        for item in request.data.get("performance_factors") or []:
            factor = PerformanceFactor.objects.filter(pk=item.get("id"), appraisal=appraisal).first()
            if not factor:
                continue
            if item.get("supervisor_assessment") is not None:
                factor.supervisor_assessment = int(item["supervisor_assessment"])
            if item.get("agreed_assessment") is not None:
                factor.agreed_assessment = int(item["agreed_assessment"])
            elif factor.supervisor_assessment is not None and factor.agreed_assessment is None:
                factor.agreed_assessment = factor.supervisor_assessment
            factor.save()

        if "overall_comment" in request.data:
            appraisal.supervisor_overall_comment = request.data["overall_comment"] or ""

        appraisal.calculate_scores()
        if request.data.get("submit", False):
            appraisal.status = "HR_REVIEW"
            appraisal.supervisor_completed_at = timezone.now()
        else:
            appraisal.status = "SUPERVISOR_REVIEW"
        appraisal.save()

        appraisal.refresh_from_db()
        return Response(AppraisalDetailSerializer(appraisal).data)


class StrategicObjectiveAdminListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = StrategicObjectiveSerializer
    queryset = StrategicObjective.objects.all().order_by("code")

    def list(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.view_strategicobjective"):
            return Response({"detail": "You do not have permission to view strategic objectives."}, status=403)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.add_strategicobjective"):
            return Response({"detail": "You do not have permission to create strategic objectives."}, status=403)
        return super().create(request, *args, **kwargs)


class StrategicObjectiveDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = StrategicObjectiveSerializer
    queryset = StrategicObjective.objects.all()

    def retrieve(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.view_strategicobjective"):
            return Response({"detail": "You do not have permission to view strategic objectives."}, status=403)
        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.change_strategicobjective"):
            return Response({"detail": "You do not have permission to update strategic objectives."}, status=403)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.delete_strategicobjective"):
            return Response({"detail": "You do not have permission to delete strategic objectives."}, status=403)
        return super().destroy(request, *args, **kwargs)


class AppraisalReportsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not request.user.has_perm("appraisal.view_appraisal"):
            return Response({"detail": "You do not have permission to view appraisal reports."}, status=403)

        cycle_id = request.query_params.get("cycle")
        appraisals = Appraisal.objects.select_related("staff", "cycle")
        if cycle_id:
            appraisals = appraisals.filter(cycle_id=cycle_id)

        total = appraisals.count()
        completed = appraisals.filter(status="ACKNOWLEDGED").count()
        avg_score = appraisals.filter(overall_score__isnull=False).aggregate(Avg("overall_score"))["overall_score__avg"]

        return Response({
            "total_appraisals": total,
            "completed": completed,
            "completion_rate": round((completed / total) * 100, 1) if total else 0,
            "avg_score": round(float(avg_score), 2) if avg_score else None,
            "rating_distribution": {
                "exceptional": appraisals.filter(overall_rating="EXCEPTIONAL").count(),
                "excellent": appraisals.filter(overall_rating="EXCELLENT").count(),
                "satisfactory": appraisals.filter(overall_rating="SATISFACTORY").count(),
                "unsatisfactory": appraisals.filter(overall_rating="UNSATISFACTORY").count(),
            },
            "status_breakdown": {
                status: appraisals.filter(status=status).count()
                for status, _ in Appraisal.APPRAISAL_STATUS_CHOICES
            },
        })


class AppraisalExportView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, cycle_id):
        if not request.user.has_perm("appraisal.view_appraisal"):
            return Response({"detail": "You do not have permission to export appraisals."}, status=403)

        cycle = AppraisalCycle.objects.filter(pk=cycle_id).first()
        if not cycle:
            return Response({"detail": "Cycle not found."}, status=404)

        appraisals = Appraisal.objects.filter(cycle=cycle).select_related("staff", "supervisor")
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "Staff", "Supervisor", "Status", "Overall rating", "Overall score", "Cycle",
        ])
        for a in appraisals:
            writer.writerow([
                a.staff.get_full_name,
                a.supervisor.get_full_name if a.supervisor else "",
                a.status,
                a.overall_rating or "",
                a.overall_score or "",
                cycle.academic_year,
            ])

        response = HttpResponse(buffer.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="appraisals_{cycle.academic_year}.csv"'
        return response


class PipListCreateView(generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PerformanceImprovementPlanSerializer
    queryset = PerformanceImprovementPlan.objects.select_related(
        "appraisal__staff", "appraisal__cycle"
    ).order_by("-start_date")

    def list(self, request, *args, **kwargs):
        if not _user_can_manage_pips(request.user):
            return Response({"detail": "You do not have permission to view PIPs."}, status=403)
        return super().list(request, *args, **kwargs)

    def create(self, request, *args, **kwargs):
        if not (
            request.user.has_perm("appraisal.add_performanceimprovementplan")
            or request.user.has_perm("staff.view_pips")
        ):
            return Response({"detail": "You do not have permission to create PIPs."}, status=403)
        return super().create(request, *args, **kwargs)


class PipDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PerformanceImprovementPlanSerializer
    queryset = PerformanceImprovementPlan.objects.select_related("appraisal__staff", "appraisal__cycle")

    def retrieve(self, request, *args, **kwargs):
        if not _user_can_manage_pips(request.user):
            return Response({"detail": "You do not have permission to view PIPs."}, status=403)
        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not (
            request.user.has_perm("appraisal.change_performanceimprovementplan")
            or request.user.has_perm("staff.view_pips")
        ):
            return Response({"detail": "You do not have permission to update PIPs."}, status=403)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not request.user.has_perm("appraisal.delete_performanceimprovementplan"):
            return Response({"detail": "You do not have permission to delete PIPs."}, status=403)
        return super().destroy(request, *args, **kwargs)

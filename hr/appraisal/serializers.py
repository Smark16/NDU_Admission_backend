from rest_framework import serializers

from accounts.models import Campus

from .models import (
    Appraisal,
    AppraisalCycle,
    AppraisalObjective,
    BehavioralCompetency,
    PerformanceFactor,
    PerformanceImprovementPlan,
    StrategicObjective,
)


class AppraisalCycleListSerializer(serializers.ModelSerializer):
    campus_name = serializers.CharField(source="campus.name", read_only=True)

    class Meta:
        model = AppraisalCycle
        fields = [
            "id",
            "campus",
            "campus_name",
            "academic_year",
            "period_from",
            "period_to",
            "review_window_from",
            "review_window_to",
            "status",
            "is_active",
        ]


class AppraisalCycleCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AppraisalCycle
        fields = [
            "campus",
            "academic_year",
            "period_from",
            "period_to",
            "review_window_from",
            "review_window_to",
            "status",
            "is_active",
        ]


class AppraisalListSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.get_full_name", read_only=True)
    cycle_year = serializers.CharField(source="cycle.academic_year", read_only=True)
    supervisor_name = serializers.CharField(source="supervisor.get_full_name", read_only=True, default="")

    class Meta:
        model = Appraisal
        fields = [
            "id",
            "cycle",
            "staff",
            "staff_name",
            "supervisor",
            "supervisor_name",
            "cycle_year",
            "status",
            "overall_rating",
            "overall_score",
        ]


class AppraisalCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appraisal
        fields = ["cycle", "staff", "supervisor"]

    def create(self, validated_data):
        from hr.leave.workflow_utils import get_staff_supervisor

        staff = validated_data["staff"]
        supervisor = validated_data.get("supervisor") or get_staff_supervisor(staff)
        return Appraisal.objects.create(
            cycle=validated_data["cycle"],
            staff=staff,
            supervisor=supervisor,
            status="DRAFT",
        )


class AppraisalStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Appraisal
        fields = ["status", "hr_comments"]


class AppraisalObjectiveSerializer(serializers.ModelSerializer):
    strategic_objective_code = serializers.CharField(
        source="strategic_objective.code", read_only=True, default=None
    )

    class Meta:
        model = AppraisalObjective
        fields = [
            "id",
            "strategic_objective",
            "strategic_objective_code",
            "individual_objective",
            "indicative_tasks",
            "target_percentage",
            "baseline_percentage",
            "weight",
            "individual_score_percentage",
            "achievements",
            "supervisor_comments",
            "agreed_score",
            "action_required",
        ]
        read_only_fields = ["id"]


class StrategicObjectiveSerializer(serializers.ModelSerializer):
    class Meta:
        model = StrategicObjective
        fields = ["id", "code", "title", "description", "is_active"]


class PerformanceImprovementPlanSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="appraisal.staff.get_full_name", read_only=True)
    cycle_year = serializers.CharField(source="appraisal.cycle.academic_year", read_only=True)

    class Meta:
        model = PerformanceImprovementPlan
        fields = [
            "id",
            "appraisal",
            "staff_name",
            "cycle_year",
            "start_date",
            "end_date",
            "status",
            "improvement_areas",
            "improvement_targets",
            "support_provided",
            "progress_notes",
            "mid_pip_review_date",
            "mid_pip_review_notes",
            "final_assessment",
            "outcome_score",
        ]


class BehavioralCompetencySerializer(serializers.ModelSerializer):
    competency_label = serializers.CharField(source="get_competency_display", read_only=True)

    class Meta:
        model = BehavioralCompetency
        fields = [
            "id",
            "competency",
            "competency_label",
            "description",
            "self_assessment",
            "supervisor_assessment",
            "agreed_assessment",
        ]


class PerformanceFactorSerializer(serializers.ModelSerializer):
    factor_label = serializers.CharField(source="get_factor_display", read_only=True)

    class Meta:
        model = PerformanceFactor
        fields = [
            "id",
            "factor",
            "factor_label",
            "description",
            "is_applicable",
            "self_assessment",
            "supervisor_assessment",
            "agreed_assessment",
        ]


class AppraisalDetailSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source="staff.get_full_name", read_only=True)
    supervisor_name = serializers.CharField(source="supervisor.get_full_name", read_only=True, default="")
    cycle_year = serializers.CharField(source="cycle.academic_year", read_only=True)
    objectives = AppraisalObjectiveSerializer(many=True, read_only=True)
    behavioral_competencies = BehavioralCompetencySerializer(many=True, read_only=True)
    performance_factors = PerformanceFactorSerializer(many=True, read_only=True)

    class Meta:
        model = Appraisal
        fields = [
            "id",
            "cycle",
            "cycle_year",
            "staff",
            "staff_name",
            "supervisor",
            "supervisor_name",
            "status",
            "overall_rating",
            "overall_score",
            "objectives_score",
            "behavioral_score",
            "performance_factors_score",
            "supervisor_overall_comment",
            "hr_comments",
            "staff_acknowledgment_comment",
            "objectives",
            "behavioral_competencies",
            "performance_factors",
        ]

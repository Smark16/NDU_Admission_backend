"""Helpers for supervisor objective setting and appraisal scaffolding."""
from .models import BehavioralCompetency, PerformanceFactor

DEFAULT_CORE_VALUES = [
    ("GOD_FEARING", "Devoutly religious and lives according to a moral code inspired by belief in God."),
    ("RESPECT", "Practices active listening, kindness, courtesy, and mindfulness of others."),
    ("INTEGRITY", "Acts according to strong ethical principles even when unobserved."),
    ("TEAMWORK", "Works cooperatively with colleagues and respects their rights."),
    ("COMMITMENT", "Shows deep dedication to achieving individual and team goals."),
    ("INNOVATIVENESS", "Implements new ideas that improve team or university performance."),
    ("EQUITY", "Provides fair and impartial treatment considering unique circumstances."),
    ("EXCELLENCE", "Consistently delivers high-quality outcomes and continuous improvement."),
    ("ACCOUNTABILITY", "Takes responsibility for actions, decisions, and performance outcomes."),
]

DEFAULT_PERFORMANCE_FACTORS = [
    ("PROFESSIONAL_COMPETENCE", "Technical and professional knowledge, skills and expertise for the job."),
    ("QUALITY_OF_WORK", "Accuracy, attention to detail, efficiency and effectiveness."),
    ("WORK_RELATIONSHIPS", "Effectiveness working with teams and maintaining a positive attitude."),
    (
        "LEADERSHIP_SKILLS",
        "Ability to plan, organize, delegate, lead, motivate and develop staff (managers/supervisors).",
    ),
]


def ensure_appraisal_assessment_scaffold(appraisal):
    """Create behavioral competencies and performance factors if missing."""
    if not appraisal.behavioral_competencies.exists():
        for code, description in DEFAULT_CORE_VALUES:
            BehavioralCompetency.objects.get_or_create(
                appraisal=appraisal,
                competency=code,
                defaults={"description": description},
            )

    if not appraisal.performance_factors.exists():
        staff_is_supervisor = bool(
            appraisal.staff.is_supervisor or appraisal.staff.is_director or appraisal.staff.is_hr
        )
        for code, description in DEFAULT_PERFORMANCE_FACTORS:
            PerformanceFactor.objects.get_or_create(
                appraisal=appraisal,
                factor=code,
                defaults={
                    "description": description,
                    "is_applicable": code != "LEADERSHIP_SKILLS" or staff_is_supervisor,
                },
            )

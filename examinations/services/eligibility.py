"""Exam sitting eligibility from CA marks, enrollment, and admission status."""
from decimal import Decimal

from admissions.models import AdmittedStudent
from Programs.models import StudentCourseUnitEnrollment

from ..models import AssessmentPolicy, CourseUnitResult
from .policy_resolver import resolve_assessment_policy


def evaluate_exam_eligibility(
    enrollment: StudentCourseUnitEnrollment,
    *,
    policy: AssessmentPolicy | None = None,
    result: CourseUnitResult | None = None,
    allow_admin_override: bool = False,
) -> dict:
    """
    Returns eligibility for end-of-semester exam sitting.

    eligible: True when student may sit (CA >= policy threshold, enrolled, not revoked).
  """
    policy = policy or resolve_assessment_policy(enrollment=enrollment)
    if result is None:
        result = getattr(enrollment, "course_result", None)

    reasons: list[str] = []
    blockers: list[str] = []

    if enrollment.status != "enrolled":
        blockers.append(f"Course enrollment status is '{enrollment.status}', not enrolled.")

    student = enrollment.student
    if student.application and student.application.is_revoked:
        blockers.append("Student admission has been revoked.")

    ca_mark = result.ca_mark if result else None
    min_ca = policy.min_ca_to_sit_exam if policy else Decimal("17.5")
    ca_max = policy.ca_max if policy else Decimal("40")

    if ca_mark is None:
        blockers.append("No continuous assessment (CA) mark entered yet.")
    elif ca_mark < min_ca:
        blockers.append(
            f"CA {ca_mark} is below the minimum {min_ca} (of {ca_max}) required to sit the exam."
        )
    else:
        reasons.append(f"CA {ca_mark} meets the sit threshold (≥ {min_ca}).")

    failed_published = (
        result is not None
        and result.status == CourseUnitResult.STATUS_PUBLISHED
        and result.is_pass is False
    )

    eligible = len(blockers) == 0
    if allow_admin_override:
        eligible = True
        reasons.append("Admin override applied.")

    return {
        "eligible": eligible,
        "reasons": reasons,
        "blockers": blockers,
        "ca_mark": str(ca_mark) if ca_mark is not None else None,
        "min_ca_to_sit_exam": str(min_ca),
        "exam_sitting_allowed": result.exam_sitting_allowed if result else False,
        "failed_published": failed_published,
        "has_published_result": bool(
            result and result.status == CourseUnitResult.STATUS_PUBLISHED
        ),
    }


def sitting_row_for_enrollment(
    enrollment: StudentCourseUnitEnrollment,
    *,
    policy: AssessmentPolicy | None = None,
    session_type: str = "regular",
) -> dict:
    """Serialize one student row for a sitting list."""
    student: AdmittedStudent = enrollment.student
    eligibility = evaluate_exam_eligibility(enrollment, policy=policy)
    result = getattr(enrollment, "course_result", None)

    return {
        "enrollment_id": enrollment.id,
        "reg_no": student.reg_no or "",
        "student_name": student.full_name or "",
        "ca_mark": str(result.ca_mark) if result and result.ca_mark is not None else None,
        "final_mark": str(result.final_mark) if result and result.final_mark is not None else None,
        "grade_letter": result.grade_letter if result else "",
        "result_status": result.status if result else None,
        "is_pass": result.is_pass if result else None,
        "eligible_to_sit": eligibility["eligible"],
        "eligibility": eligibility,
        "session_type": session_type,
    }

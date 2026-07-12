"""Exam sitting eligibility from CA marks, enrollment, admission status, and attendance %."""
from decimal import Decimal

from admissions.models import AdmittedStudent
from Programs.attendance_stats import student_course_attendance_summary
from Programs.models import StudentCourseUnitEnrollment

from ..models import AssessmentPolicy, CourseUnitResult
from .policy_resolver import resolve_assessment_policy


def evaluate_exam_eligibility(
    enrollment: StudentCourseUnitEnrollment,
    *,
    policy: AssessmentPolicy | None = None,
    result: CourseUnitResult | None = None,
    allow_admin_override: bool = False,
    allow_failed_published_retake: bool = False,
) -> dict:
    """
    Returns eligibility for end-of-semester exam sitting.

    eligible: True when student may sit (CA >= policy threshold, attendance %, enrolled, not revoked).
    """
    policy = policy or resolve_assessment_policy(enrollment=enrollment)
    if result is None:
        result = getattr(enrollment, "course_result", None)

    reasons: list[str] = []
    blockers: list[str] = []

    failed_published = (
        result is not None
        and result.status == CourseUnitResult.STATUS_PUBLISHED
        and result.is_pass is False
    )

    if enrollment.status != "enrolled" and not (
        allow_failed_published_retake and failed_published
    ):
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

    attendance = student_course_attendance_summary(student, enrollment.course_unit)
    attendance_percent = attendance.get("attendance_percent")
    min_attendance = attendance.get("min_percent_required")
    if attendance.get("sessions_taken", 0) > 0 and attendance_percent is not None:
        if not attendance.get("meets_threshold"):
            blockers.append(
                f"Attendance {attendance_percent}% is below the minimum "
                f"{min_attendance}% required to sit the exam "
                f"({attendance['sessions_attended']}/{attendance['sessions_taken']} sessions)."
            )
        else:
            reasons.append(
                f"Attendance {attendance_percent}% meets the sit threshold (≥ {min_attendance}%)."
            )
    else:
        reasons.append("No lecture attendance sessions recorded yet for this course.")

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
        "attendance_percent": attendance_percent,
        "min_attendance_percent_to_sit_exam": min_attendance,
        "attendance_sessions_taken": attendance.get("sessions_taken", 0),
        "attendance_sessions_attended": attendance.get("sessions_attended", 0),
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
    eligibility = evaluate_exam_eligibility(
        enrollment,
        policy=policy,
        allow_failed_published_retake=session_type in {"retake", "supplementary"},
    )
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

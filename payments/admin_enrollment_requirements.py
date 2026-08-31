"""Staff checks before activating academic programme enrollment (status=enrolled)."""
from __future__ import annotations

from admissions.models import AdmittedStudent

from .models import RegistrationSettings
from .student_portal_finance import commitment_payment_summary

_GENERIC_COMMITMENT_BLOCK = (
    "Commitment fee requirement not met. "
    "Ask Bursar / Finance to confirm payment before activating enrollment."
)


def programme_enrollment_access_block(student: AdmittedStudent) -> str | None:
    """Return an error if the student lacks active academic enrollment (status=enrolled)."""
    try:
        enrollment = student.programme_enrollment
    except Exception:
        return (
            "Student does not have academic programme enrollment. "
            "Activate enrollment after the commitment fee is confirmed."
        )
    if not enrollment.is_enrolled:
        status_display = enrollment.get_status_display()
        return (
            f"Academic enrollment status is '{status_display}'. "
            "Course enrolment requires status 'Enrolled' (commitment fee confirmed)."
        )
    return None


def batch_course_enrollment_block(student: AdmittedStudent) -> str | None:
    """
    Gate admin batch/course-unit enrollment.

    Always requires commitment fee paid and academic programme enrollment
    (SPE status Enrolled). Other Registration Settings toggles (admission
    approval, intake batch) still apply when enabled.
    """
    settings = RegistrationSettings.get_settings()

    if settings.require_admission_approval and not student.is_admitted:
        return "Student must be admitted before they can be enrolled in batch courses."

    # Commitment fee is required for programme enrollment activation.
    commitment_block = admin_programme_enrollment_activation_block(
        student, target_status="enrolled"
    )
    if commitment_block:
        return commitment_block

    access = programme_enrollment_access_block(student)
    if access:
        return access

    if settings.require_enrollment and not student.admitted_batch_id:
        return "Student must be assigned to an admission intake batch before batch course enrollment."

    return None


def student_eligible_for_batch_course_enrollment(student: AdmittedStudent) -> bool:
    return batch_course_enrollment_block(student) is None


def admin_programme_enrollment_activation_block(
    student: AdmittedStudent,
    *,
    target_status: str,
    reveal_amounts: bool = True,
) -> str | None:
    """Return an error message if staff cannot set SPE to target_status, else None."""
    if target_status != "enrolled":
        return None

    if not student.is_admitted:
        return "Student must be admitted before academic enrollment can be activated."

    app = getattr(student, "application", None)
    if app and getattr(app, "is_revoked", False):
        return "Cannot activate enrollment for a student whose admission has been revoked."

    # Policy override: Registration settings → auto-enroll on admission.
    if getattr(RegistrationSettings.get_settings(), "auto_enroll_on_admission", False):
        return None

    summary = commitment_payment_summary(student)
    if summary["commitment_met"]:
        return None

    if not reveal_amounts:
        return _GENERIC_COMMITMENT_BLOCK

    threshold = summary["commitment_threshold"]
    paid = summary["commitment_paid_ugx"]
    balance = summary["commitment_balance"]
    return (
        "Commitment fee requirement not met. "
        f"Paid UGX {paid:,.0f} of UGX {threshold:,.0f} required "
        f"(balance UGX {balance:,.0f}). "
        "Record the student's commitment or admission fee payment before enrolling."
    )


def admin_programme_enrollment_eligibility(student: AdmittedStudent, user=None) -> dict:
    from accounts.finance_access import user_can_view_student_finance

    can_finance = user_can_view_student_finance(user) if user is not None else False
    summary = commitment_payment_summary(student)
    auto_on_admit = bool(
        getattr(RegistrationSettings.get_settings(), "auto_enroll_on_admission", False)
    )
    block = admin_programme_enrollment_activation_block(
        student, target_status="enrolled", reveal_amounts=can_finance
    )
    app = getattr(student, "application", None)
    payload = {
        "can_activate_enrollment": block is None,
        "block_reason": block,
        "auto_enroll_on_admission": auto_on_admit,
        "is_revoked": bool(app and getattr(app, "is_revoked", False)),
        "is_admitted": bool(student.is_admitted),
        "can_view_finance": can_finance,
    }
    if can_finance:
        payload.update(
            {
                "commitment_met": summary["commitment_met"],
                "commitment_paid_ugx": summary["commitment_paid_ugx"],
                "commitment_threshold": summary["commitment_threshold"],
                "commitment_balance": summary["commitment_balance"],
                "admission_fee_paid": bool(getattr(student, "admission_fee_paid", False)),
            }
        )
    else:
        payload.update(
            {
                "commitment_met": None,
                "commitment_paid_ugx": None,
                "commitment_threshold": None,
                "commitment_balance": None,
                "admission_fee_paid": None,
            }
        )
    return payload

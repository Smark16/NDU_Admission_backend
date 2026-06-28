"""Staff checks before activating academic programme enrollment (status=enrolled)."""
from __future__ import annotations

from admissions.models import AdmittedStudent

from .models import RegistrationSettings
from .student_portal_finance import commitment_payment_summary


def admin_programme_enrollment_activation_block(
    student: AdmittedStudent,
    *,
    target_status: str,
) -> str | None:
    """Return an error message if staff cannot set SPE to target_status, else None."""
    if target_status != "enrolled":
        return None

    if not student.is_admitted:
        return "Student must be admitted before academic enrollment can be activated."

    app = getattr(student, "application", None)
    if app and getattr(app, "is_revoked", False):
        return "Cannot activate enrollment for a student whose admission has been revoked."

    settings = RegistrationSettings.get_settings()
    if getattr(settings, "auto_enroll_on_admission", False):
        return None

    summary = commitment_payment_summary(student)
    if summary["commitment_met"]:
        return None

    threshold = summary["commitment_threshold"]
    paid = summary["commitment_paid_ugx"]
    balance = summary["commitment_balance"]
    return (
        "Commitment fee requirement not met. "
        f"Paid UGX {paid:,.0f} of UGX {threshold:,.0f} required "
        f"(balance UGX {balance:,.0f}). "
        "Confirm the student's commitment or admission fee payment before enrolling."
    )


def admin_programme_enrollment_eligibility(student: AdmittedStudent) -> dict:
    summary = commitment_payment_summary(student)
    auto_skip = bool(getattr(RegistrationSettings.get_settings(), "auto_enroll_on_admission", False))
    block = admin_programme_enrollment_activation_block(student, target_status="enrolled")
    app = getattr(student, "application", None)
    return {
        "can_activate_enrollment": block is None,
        "block_reason": block,
        "commitment_met": summary["commitment_met"],
        "commitment_paid_ugx": summary["commitment_paid_ugx"],
        "commitment_threshold": summary["commitment_threshold"],
        "commitment_balance": summary["commitment_balance"],
        "admission_fee_paid": bool(getattr(student, "admission_fee_paid", False)),
        "auto_enroll_on_admission": auto_skip,
        "is_revoked": bool(app and getattr(app, "is_revoked", False)),
        "is_admitted": bool(student.is_admitted),
    }

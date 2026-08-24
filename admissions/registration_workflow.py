"""Registration clearance stages: Accounts (all) + AR documents (Year 1 Term 1 only)."""
from __future__ import annotations

from admissions.models import AdmittedStudent


def student_curriculum_year_term(student: AdmittedStudent) -> tuple[int, int]:
    """Current programme year/term; defaults to Year 1 Term 1 when enrollment is missing."""
    try:
        enr = student.programme_enrollment
        y = int(getattr(enr, "current_year_of_study", None) or 1)
        t = int(getattr(enr, "current_term_number", None) or 1)
        if y >= 1 and t >= 1:
            return y, t
    except Exception:
        pass
    return 1, 1


def requires_physical_document_verification(student: AdmittedStudent) -> bool:
    """AR hard-copy document verification applies only to Year 1 Semester/Term 1."""
    year, term = student_curriculum_year_term(student)
    return year == 1 and term == 1


def registration_stage_for_student(student: AdmittedStudent) -> str:
    """
    Desk / Bonafide workflow stages.

    Course registration opens after Accounts clearance for every student.
    Year 1 Term 1 also has an AR document-verification step (does not block
    registration by itself — tracked for AR / ID workflows).
    """
    requires_docs = requires_physical_document_verification(student)
    accounts_ok = bool(getattr(student, "accounts_registration_cleared", False))
    docs_ok = bool(getattr(student, "physical_documents_verified", False))
    paid = bool(getattr(student, "admission_fee_paid", False))
    if not paid:
        from admissions.temporary_access import accounts_clearance_waives_fee_threshold

        if not accounts_clearance_waives_fee_threshold(student):
            return "unpaid"
    if not accounts_ok:
        return "awaiting_accounts"
    # Accounts cleared → ready to register (all students).
    # Y1T1 may still be awaiting AR docs as a parallel desk step.
    if requires_docs and not docs_ok:
        return "awaiting_docs"
    return "ready"


REGISTRATION_STAGE_LABELS = {
    "unpaid": "1. Payment pending",
    "awaiting_accounts": "2. Awaiting Accounts clear",
    "awaiting_docs": "Accounts cleared — AR docs pending (Y1 Sem 1)",
    "ready": "Cleared — ready to register",
    # Legacy alias used by older clients / filters
    "docs_verified": "Cleared — ready to register",
}


def registration_stage_label(stage: str) -> str:
    return REGISTRATION_STAGE_LABELS.get(stage, "—")


ADMISSION_REVOKE_OR_DELETE_BLOCKED = (
    "This student is accounts-cleared and registered (verified roster). "
    "Admission cannot be revoked or deleted."
)

ADMISSION_DELETE_BLOCKED_SUPER_ADMIN_HINT = (
    "This student is accounts-cleared and registered (verified roster). "
    "Admission cannot be deleted. Use Revoke Admission instead."
)


def user_can_revoke_locked_admission(user) -> bool:
    """Who may revoke a verified / accounts-cleared+registered admission."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    from accounts.super_admin import user_is_super_admin

    if user_is_super_admin(user):
        return True
    try:
        return bool(
            user.has_perm("admissions.revoke_admission")
            or user.has_perm("admissions.change_admittedstudent")
        )
    except Exception:
        return False


def admission_revoke_or_delete_blocked_reason(
    student: AdmittedStudent | None,
    user=None,
    *,
    action: str = "delete",
) -> str | None:
    """
    Official students cannot be withdrawn from the system by normal staff.

    Locked when they are on the verified roster (physical documents verified)
    or they are both accounts-cleared and registered.

    Super Admin (or staff with revoke/change admission permission) may
    **revoke** locked admissions — pass ``action="revoke"`` and the acting
    ``user``. Delete stays blocked for everyone.
    """
    if student is None:
        return None
    verified = bool(getattr(student, "physical_documents_verified", False))
    cleared = bool(getattr(student, "accounts_registration_cleared", False))
    registered = bool(getattr(student, "is_registered", False))
    locked = verified or (cleared and registered)
    if not locked:
        return None

    if action == "revoke" and user_can_revoke_locked_admission(user):
        return None

    if action == "revoke":
        return ADMISSION_REVOKE_OR_DELETE_BLOCKED
    if user_can_revoke_locked_admission(user):
        return ADMISSION_DELETE_BLOCKED_SUPER_ADMIN_HINT
    return ADMISSION_REVOKE_OR_DELETE_BLOCKED

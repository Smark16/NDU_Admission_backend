"""Per-student exemptions from scheduled other fees (hostel, etc.)."""
from __future__ import annotations

from admissions.models import AdmittedStudent
from payments.models import StudentFeeExemption


def active_fee_exemptions_for_student(student: AdmittedStudent) -> list[StudentFeeExemption]:
    return list(
        StudentFeeExemption.objects.filter(student=student, is_active=True).select_related(
            "fee_head", "created_by", "revoked_by"
        )
    )


def is_fee_head_exempted(
    exemptions: list[StudentFeeExemption],
    fee_head_id: int | None,
    *,
    payable_year: int | None = None,
    payable_term: int | None = None,
) -> bool:
    if not fee_head_id:
        return False
    for row in exemptions:
        if row.fee_head_id != fee_head_id:
            continue
        if row.matches_milestone(payable_year, payable_term):
            return True
    return False


def exemption_to_dict(row: StudentFeeExemption) -> dict:
    scope = "All years / terms"
    if row.payable_year_of_study:
        scope = f"Year {row.payable_year_of_study}"
        if row.payable_term_number:
            scope += f", Term {row.payable_term_number}"

    def _user_label(user) -> str | None:
        if not user:
            return None
        full = (getattr(user, "get_full_name", lambda: "")() or "").strip()
        return full or getattr(user, "username", None) or getattr(user, "email", None)

    return {
        "id": row.id,
        "fee_head_id": row.fee_head_id,
        "fee_head_code": row.fee_head.code if row.fee_head_id else "",
        "fee_head_name": row.fee_head.name if row.fee_head_id else "",
        "payable_year_of_study": row.payable_year_of_study,
        "payable_term_number": row.payable_term_number,
        "scope_label": scope,
        "reason": row.reason or "",
        "is_active": row.is_active,
        "created_by": _user_label(row.created_by),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "revoked_by": _user_label(row.revoked_by),
        "revoked_at": row.revoked_at.isoformat() if row.revoked_at else None,
    }

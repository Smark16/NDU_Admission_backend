"""Course registration eligibility: tuition payment threshold + settings gates."""
from __future__ import annotations

from decimal import Decimal

from admissions.models import AdmittedStudent

from .models import RegistrationSettings
from .registration_gates import (
    enrollment_block,
    get_programme_enrollment_status,
    settings_block_message,
)
from .student_fee_pricing import is_international_student, paid_by_currency
from .student_payment_allocation import build_finance_allocation


def _compute_tuition_eligibility(student: AdmittedStudent, settings: RegistrationSettings) -> dict:
    """Tuition % gate only — independent of commitment / programme enrollment gates."""
    if settings.skip_tuition_check:
        international = is_international_student(student)
        paid_by = paid_by_currency(student)
        total_paid = float(sum(paid_by.values(), Decimal("0")))
        return {
            "tuition_eligible": True,
            "percentage_paid": 100.0,
            "minimum_required": float(settings.min_tuition_payment_percentage),
            "total_required": 0.0,
            "total_paid": total_paid,
            "balance": 0.0,
            "display_currency": "USD" if international else "UGX",
            "tuition_check_skipped": True,
            "tuition_message": "Tuition payment threshold is currently disabled. You may register.",
        }

    alloc = build_finance_allocation(student)
    international = alloc.international
    req_by = alloc.required_by_currency
    paid_by = {k: Decimal(str(v)) for k, v in alloc.paid_by_currency.items()}
    min_pct = Decimal(str(settings.min_tuition_payment_percentage)) / Decimal("100")

    if not req_by:
        return {
            "tuition_eligible": True,
            "percentage_paid": 100.0,
            "minimum_required": float(settings.min_tuition_payment_percentage),
            "total_required": 0.0,
            "total_paid": float(sum(paid_by.values(), Decimal("0"))),
            "balance": 0.0,
            "display_currency": "USD" if international else "UGX",
            "tuition_check_skipped": False,
            "tuition_message": "No semester tuition rules apply yet; you may register when courses are available.",
        }

    primary_ccy = alloc.primary_currency
    tr = Decimal(str(alloc.total_required))
    tp = paid_by.get(primary_ccy, Decimal("0"))
    pct = float((tp / tr * Decimal("100"))) if tr > 0 else 0.0

    payment_ok = True
    short_parts = []
    for ccy, req in req_by.items():
        if req <= 0:
            continue
        paid = paid_by.get(ccy, Decimal("0"))
        need = Decimal(str(req)) * min_pct
        if paid < need:
            payment_ok = False
            short_parts.append(f"{ccy} {float(need - paid):,.2f}")

    if not payment_ok:
        pay_msg = (
            f"Pay at least {float(settings.min_tuition_payment_percentage):.0f}% of tuition per currency. "
            f"Shortfall: {', '.join(short_parts)}."
        )
    else:
        pay_msg = "You meet the minimum tuition payment for registration."

    return {
        "tuition_eligible": payment_ok,
        "percentage_paid": round(pct, 1),
        "minimum_required": float(settings.min_tuition_payment_percentage),
        "total_required": float(tr),
        "total_paid": float(tp),
        "balance": float(alloc.balance),
        "display_currency": primary_ccy,
        "tuition_check_skipped": False,
        "tuition_message": pay_msg,
    }


def build_registration_eligibility_payload(student: AdmittedStudent) -> dict:
    settings = RegistrationSettings.get_settings()
    enroll_info = get_programme_enrollment_status(student)
    tuition = _compute_tuition_eligibility(student, settings)

    block_messages: list[str] = []
    settings_msg = settings_block_message(settings)
    if settings_msg:
        block_messages.append(settings_msg)

    enroll_msg = enrollment_block(student, settings)
    if enroll_msg:
        block_messages.append(enroll_msg)

    if not tuition["tuition_eligible"]:
        block_messages.append(tuition["tuition_message"])

    is_eligible = len(block_messages) == 0
    message = block_messages[0] if block_messages else tuition["tuition_message"]

    return {
        "is_eligible": is_eligible,
        "percentage_paid": tuition["percentage_paid"],
        "minimum_required": tuition["minimum_required"],
        "total_required": tuition["total_required"],
        "total_paid": tuition["total_paid"],
        "balance": tuition["balance"],
        "display_currency": tuition["display_currency"],
        "tuition_check_skipped": tuition["tuition_check_skipped"],
        "tuition_eligible": tuition["tuition_eligible"],
        "message": message,
        "block_messages": block_messages,
        **enroll_info,
    }

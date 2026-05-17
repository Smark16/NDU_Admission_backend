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


def build_registration_eligibility_payload(student: AdmittedStudent) -> dict:
    settings = RegistrationSettings.get_settings()

    # Always include enrollment status in the response
    enroll_info = get_programme_enrollment_status(student)

    # ── Gate 1 + 2: settings window + admission/enrollment gates ──────────────
    msg = settings_block_message(settings) or enrollment_block(student, settings)
    if msg:
        return {
            "is_eligible": False,
            "percentage_paid": 0.0,
            "minimum_required": float(settings.min_tuition_payment_percentage),
            "total_required": 0.0,
            "total_paid": 0.0,
            "balance": 0.0,
            "display_currency": "UGX",
            "tuition_check_skipped": settings.skip_tuition_check,
            "message": msg,
            **enroll_info,
        }

    # ── Gate 3 (optional): tuition payment threshold ──────────────────────────
    # If skip_tuition_check is True, bypass the payment % gate entirely.
    if settings.skip_tuition_check:
        international = is_international_student(student)
        paid_by = paid_by_currency(student)
        total_paid = float(sum(paid_by.values(), Decimal("0")))
        return {
            "is_eligible": True,
            "percentage_paid": 100.0,
            "minimum_required": float(settings.min_tuition_payment_percentage),
            "total_required": 0.0,
            "total_paid": total_paid,
            "balance": 0.0,
            "display_currency": "USD" if international else "UGX",
            "tuition_check_skipped": True,
            "message": "Tuition payment threshold is currently disabled. You may register.",
            **enroll_info,
        }

    # ── Normal path: compute tuition % and check against threshold ─────────────
    alloc = build_finance_allocation(student)
    international = alloc.international
    req_by = alloc.required_by_currency
    paid_by = {k: Decimal(str(v)) for k, v in alloc.paid_by_currency.items()}
    min_pct = Decimal(str(settings.min_tuition_payment_percentage)) / Decimal("100")

    if not req_by:
        return {
            "is_eligible": True,
            "percentage_paid": 100.0,
            "minimum_required": float(settings.min_tuition_payment_percentage),
            "total_required": 0.0,
            "total_paid": float(sum(paid_by.values(), Decimal("0"))),
            "balance": 0.0,
            "display_currency": "USD" if international else "UGX",
            "tuition_check_skipped": False,
            "message": "No semester tuition rules apply yet; you may register when courses are available.",
            **enroll_info,
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
        "is_eligible": payment_ok,
        "percentage_paid": round(pct, 1),
        "minimum_required": float(settings.min_tuition_payment_percentage),
        "total_required": float(tr),
        "total_paid": float(tp),
        "balance": float(alloc.balance),
        "display_currency": primary_ccy,
        "tuition_check_skipped": False,
        "message": pay_msg,
        **enroll_info,
    }

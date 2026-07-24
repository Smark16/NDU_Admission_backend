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
from .student_payment_allocation import tuition_registration_totals


def _compute_tuition_eligibility(student: AdmittedStudent, settings: RegistrationSettings) -> dict:
    """Tuition % gate only — independent of commitment / programme enrollment gates."""
    min_required_pct = float(settings.min_tuition_payment_percentage)

    if settings.skip_tuition_check:
        international = is_international_student(student)
        paid_by = paid_by_currency(student)
        total_paid = float(sum(paid_by.values(), Decimal("0")))
        return {
            "tuition_eligible": True,
            "percentage_paid": 100.0,
            "minimum_required": min_required_pct,
            "total_required": 0.0,
            "total_paid": total_paid,
            "balance": 0.0,
            "display_currency": "USD" if international else "UGX",
            "tuition_check_skipped": True,
            "tuition_message": "Tuition payment threshold is currently disabled. You may register.",
        }

    min_pct = Decimal(str(min_required_pct)) / Decimal("100")
    totals = tuition_registration_totals(student, current_term_only=True)

    if min_required_pct > 0 and not totals["has_tuition_rules"]:
        return {
            "tuition_eligible": False,
            "percentage_paid": 0.0,
            "minimum_required": min_required_pct,
            "total_required": 0.0,
            "total_paid": 0.0,
            "balance": 0.0,
            "display_currency": totals["primary_currency"],
            "tuition_check_skipped": False,
            "tuition_message": (
                "Semester tuition is not configured for your current term "
                f"(Year {totals['current_year_of_study']}, Term {totals['current_term_number']}). "
                "You cannot register until tuition fees are set up for your programme batch."
            ),
        }

    by_ccy = totals["by_currency"]
    primary_ccy = totals["primary_currency"]
    tr = totals["total_required"]
    tp = totals["total_paid_on_tuition"]
    pct = totals["percentage_paid"]

    payment_ok = True
    short_parts: list[str] = []
    for ccy, bucket in by_ccy.items():
        req = bucket["required"]
        if req <= 0:
            continue
        paid = bucket["paid"]
        need = req * min_pct
        if paid < need:
            payment_ok = False
            short_parts.append(f"{ccy} {float(need - paid):,.2f}")

    if not payment_ok:
        pay_msg = (
            f"Pay at least {min_required_pct:.0f}% of your current semester tuition. "
            f"Shortfall: {', '.join(short_parts)}."
        )
    else:
        pay_msg = "You meet the minimum tuition payment for registration."

    balance = max(tr - tp, Decimal("0"))

    return {
        "tuition_eligible": payment_ok,
        "percentage_paid": pct,
        "minimum_required": min_required_pct,
        "total_required": float(tr),
        "total_paid": float(tp),
        "balance": float(balance),
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

    accounts_cleared = bool(getattr(student, "accounts_registration_cleared", False))
    if not accounts_cleared:
        block_messages.append(
            "Accounts has not cleared you yet. Course registration (and your registration card) "
            "open only after Accounts confirms payment — for new and continuing students."
        )

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
        "accounts_registration_cleared": accounts_cleared,
        "message": message,
        "block_messages": block_messages,
        **enroll_info,
    }

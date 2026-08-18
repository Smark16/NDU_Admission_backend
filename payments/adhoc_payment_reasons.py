"""Canonical SchoolPay AdhocPayments `reason` labels.

SchoolPay (and later ERP finance reports) group adhoc collections by this
exact string. Keep values short and stable.

Do not interpolate student IDs or amounts here — those belong on local
payment notes / receipt rows. Student-code tuition payments are a different
rail and must never reuse these labels.
"""
from __future__ import annotations

APPLICATION_FEE = "Application Fee"
EXEMPTION_PAYMENTS = "Exemption payments"
ID_CARD_PAYMENTS = "ID card payments"
CHANGE_COURSE_PAYMENTS = "Change of course payments"

ADHOC_PAYMENT_REASONS: dict[str, str] = {
    "application_fee": APPLICATION_FEE,
    "exemption": EXEMPTION_PAYMENTS,
    "id_card": ID_CARD_PAYMENTS,
    "change_course": CHANGE_COURSE_PAYMENTS,
}


def schoolpay_adhoc_reason(kind: str) -> str:
    try:
        return ADHOC_PAYMENT_REASONS[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown adhoc payment kind: {kind}") from exc

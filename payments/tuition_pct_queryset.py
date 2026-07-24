"""Filter admitted students by semester tuition payment percentage."""
from __future__ import annotations

from payments.models import RegistrationSettings
from payments.registration_eligibility import student_tuition_eligible


def registration_min_tuition_pct() -> float:
    settings = RegistrationSettings.get_settings()
    return float(settings.min_tuition_payment_percentage or 60)


def student_meets_tuition_pct(student, min_pct: float | None = None) -> bool:
    """
    True when the student meets the registration tuition % gate
    (same rules as course registration eligibility tuition check).

    ``min_pct`` is reserved for an explicit override; when omitted, uses
    RegistrationSettings.min_tuition_payment_percentage.
    """
    if min_pct is not None:
        from payments.student_payment_allocation import tuition_registration_totals
        from decimal import Decimal

        settings = RegistrationSettings.get_settings()
        if settings.skip_tuition_check:
            return True
        totals = tuition_registration_totals(student, current_term_only=True)
        if float(min_pct) > 0 and not totals["has_tuition_rules"]:
            return False
        req = totals["total_required"]
        if req <= 0:
            return float(min_pct) <= 0
        need = Decimal(str(req)) * (Decimal(str(min_pct)) / Decimal("100"))
        return totals["total_paid_on_tuition"] >= need

    return student_tuition_eligible(student)


def filter_by_tuition_pct_met(qs, met: bool, *, min_pct: float | None = None, max_scan: int = 8000):
    """
    Keep students who meet (or do not meet) the tuition % gate.

    Evaluates finance allocation in Python — prefer with a narrowed queue
    (e.g. not yet Accounts-cleared). Caps scan to avoid runaway list queries.
    """
    ids: list[int] = []
    scanned = 0
    for student in qs.order_by("id").iterator(chunk_size=50):
        scanned += 1
        if scanned > max_scan:
            break
        meets = student_meets_tuition_pct(student, min_pct)
        if meets == bool(met):
            ids.append(student.id)
    if not ids:
        return qs.none()
    return qs.filter(id__in=ids)

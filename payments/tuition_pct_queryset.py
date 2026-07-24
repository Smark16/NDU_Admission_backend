"""Filter admitted students by semester tuition payment percentage."""
from __future__ import annotations

import logging

from django.db.models import Exists, OuterRef, Q

from payments.models import RegistrationSettings, StudentTuitionPayment, TuitionLedger
from payments.registration_eligibility import student_tuition_eligible

logger = logging.getLogger(__name__)


def registration_min_tuition_pct() -> float:
    settings = RegistrationSettings.get_settings()
    return float(settings.min_tuition_payment_percentage or 60)


def _has_payment_activity_q() -> Q:
    """Cheap prefilter: anyone with portal/ledger credit or commitment flag."""
    portal_paid = Exists(
        StudentTuitionPayment.objects.filter(
            student_id=OuterRef("pk"),
            status="completed",
            is_waived=False,
        )
    )
    ledger_paid = Exists(
        TuitionLedger.objects.filter(
            student_id=OuterRef("pk"),
            transaction_completion_status="Completed",
        )
    )
    return Q(admission_fee_paid=True) | portal_paid | ledger_paid


def student_meets_tuition_pct(student, min_pct: float | None = None) -> bool:
    """
    True when the student meets the registration tuition % gate
    (same rules as course registration eligibility tuition check).
    """
    try:
        if min_pct is not None:
            from decimal import Decimal

            from payments.student_payment_allocation import tuition_registration_totals

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
    except Exception:
        logger.exception("tuition %% check failed for student id=%s", getattr(student, "pk", None))
        return False


def filter_by_tuition_pct_met(qs, met: bool, *, min_pct: float | None = None, max_scan: int = 1500):
    """
    Keep students who meet (or do not meet) the tuition % gate.

    Prefers students with payment activity, then evaluates finance in Python.
    Caps scan so the Bonafide list cannot time out the request.
    """
    # Narrow first — evaluating finance for every uncleared student (default False) times out.
    if met:
        candidates = qs.filter(_has_payment_activity_q())
    else:
        candidates = qs

    ids: list[int] = []
    scanned = 0
    for student in candidates.order_by("id").iterator(chunk_size=25):
        scanned += 1
        if scanned > max_scan:
            logger.warning(
                "tuition_pct filter stopped after scanning %s students (max_scan=%s)",
                scanned - 1,
                max_scan,
            )
            break
        meets = student_meets_tuition_pct(student, min_pct)
        if meets == bool(met):
            ids.append(student.id)

    if not ids:
        return qs.none()
    return qs.filter(id__in=ids)

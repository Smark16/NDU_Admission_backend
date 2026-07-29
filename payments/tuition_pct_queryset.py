"""Filter admitted students by semester tuition payment percentage (live evaluation)."""
from __future__ import annotations

import logging

from django.db.models import Exists, OuterRef, Q

from payments.models import RegistrationSettings, StudentTuitionPayment, TuitionLedger
from payments.registration_eligibility import student_tuition_eligible

logger = logging.getLogger(__name__)


def registration_min_tuition_pct() -> float:
    """Current admin threshold from RegistrationSettings (same as /registration_settings)."""
    settings = RegistrationSettings.get_settings()
    return float(settings.min_tuition_payment_percentage or 0)


def _has_tuition_credit_q() -> Q:
    """Portal/ledger tuition credit (commitment flag alone is not enough)."""
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
    return portal_paid | ledger_paid


def student_meets_tuition_pct(student, min_pct: float | None = None) -> bool:
    """
    True when the student meets the registration tuition % gate
    (same rules as course registration eligibility tuition check).

    When ``min_pct`` is None, uses RegistrationSettings.min_tuition_payment_percentage.
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


def filter_by_tuition_pct_met(qs, met: bool, *, min_pct: float | None = None):
    """
    Keep students who meet (or do not meet) the tuition % gate.

    Always evaluates live against RegistrationSettings (or explicit ``min_pct``)
    so Bonafide admin filters stay accurate when the threshold changes.
    No cross-request DB cache — admins only, accuracy over stale speed.

    Optimizations (without sacrificing accuracy):
    - skip_tuition_check short-circuits
    - students with no portal/ledger credit cannot meet → bulk include/exclude
    - only credit-holders run the finance allocation check
    """
    settings = RegistrationSettings.get_settings()
    if settings.skip_tuition_check:
        return qs if met else qs.none()

    # Resolve threshold once (matches GET /api/payments/registration_settings).
    threshold = (
        float(min_pct)
        if min_pct is not None
        else float(settings.min_tuition_payment_percentage or 0)
    )

    credit_q = _has_tuition_credit_q()
    with_credit = qs.filter(credit_q)
    without_credit = qs.exclude(credit_q)

    if met:
        # No tuition credit ⇒ cannot meet a positive threshold.
        if threshold <= 0:
            candidates = qs
        else:
            candidates = with_credit
        return _live_filter_ids(candidates, want_met=True, min_pct=threshold)

    # unpaid / below threshold: everyone without credit + credit-holders who fail the gate
    no_credit_ids = list(without_credit.values_list("id", flat=True))
    below_ids = _live_eval_ids(with_credit, want_met=False, min_pct=threshold)
    combined = list({*no_credit_ids, *below_ids})
    if not combined:
        return qs.none()
    return qs.filter(id__in=combined)


def _live_filter_ids(candidates, *, want_met: bool, min_pct: float):
    ids = _live_eval_ids(candidates, want_met=want_met, min_pct=min_pct)
    if not ids:
        return candidates.none()
    return candidates.filter(id__in=ids)


def _live_eval_ids(candidates, *, want_met: bool, min_pct: float) -> list[int]:
    """Run live finance checks; return matching primary keys."""
    # Prefetch relations commonly touched by allocation / eligibility.
    qs = candidates.select_related(
        "application",
        "admitted_program",
        "admitted_batch",
        "intended_program_batch",
        "programme_enrollment__program_batch",
    ).order_by("id")

    matched: list[int] = []
    scanned = 0
    for student in qs.iterator(chunk_size=50):
        scanned += 1
        meets = student_meets_tuition_pct(student, min_pct)
        if meets == bool(want_met):
            matched.append(student.id)

    logger.info(
        "tuition_pct live filter scanned=%s matched=%s want_met=%s min_pct=%s",
        scanned,
        len(matched),
        want_met,
        min_pct,
    )
    return matched

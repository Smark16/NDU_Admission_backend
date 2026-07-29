"""Filter admitted students by semester tuition payment percentage."""
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
    Same gate as course registration (student_tuition_eligible).

    ``min_pct`` is accepted for API compatibility but ignored: the live
    RegistrationSettings.min_tuition_payment_percentage is always used.
    """
    try:
        _ = min_pct
        return bool(student_tuition_eligible(student))
    except Exception:
        logger.exception(
            "tuition %% check failed for student id=%s", getattr(student, "pk", None)
        )
        return False


def filter_by_tuition_pct_met(qs, met: bool, *, min_pct: float | None = None):
    """
    Keep students who meet (or do not meet) the registration tuition % gate.

    Uses indexed ``registration_tuition_pct_met`` (same eligibility rules as registration).
    Request path stays fast for gunicorn (no multi-minute live scan that kills workers).

    Warm-up:
    - bulk-stamp students with no portal/ledger credit as unmet (cheap SQL)
    - enqueue Celery / optionally sync a tiny credit-holder sample
    - filter only rows that already have a computed cache timestamp

    Run ``python manage.py refresh_tuition_pct_cache`` after deploy for full coverage.
    """
    _ = min_pct
    settings = RegistrationSettings.get_settings()
    if settings.skip_tuition_check:
        logger.warning(
            "tuition_pct filter: skip_tuition_check=True — treating all as met"
        )
        return qs if met else qs.none()

    from payments.tuition_pct_cache import ensure_tuition_pct_cache_for_queryset

    # Keep request under gunicorn timeout: stamp + tiny sync + background backfill.
    ensure_tuition_pct_cache_for_queryset(
        qs,
        prefer_payment_activity=bool(met),
        max_sync=12,
    )

    # Only return students whose gate was computed — never silently widen the filter.
    return qs.filter(
        registration_tuition_pct_at__isnull=False,
        registration_tuition_pct_met=bool(met),
    )

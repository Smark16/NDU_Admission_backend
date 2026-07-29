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
    Same gate as course registration (student_tuition_eligible).

    ``min_pct`` is accepted for API compatibility but ignored: the live
    RegistrationSettings.min_tuition_payment_percentage is always used so
    Bonafide filters cannot drift from /api/payments/registration_settings.
    """
    try:
        # Keep signature; threshold always comes from RegistrationSettings inside
        # student_tuition_eligible → _compute_tuition_eligibility.
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

    Live evaluation only (no DB/browser cache). Uses the same rules as student
    registration eligibility, including:
    - no fee schedule / required UGX 0 ⇒ does NOT meet a positive threshold
    - commitment-only payment is not enough

    Optimizations:
    - skip_tuition_check short-circuit
    - no portal/ledger credit ⇒ cannot meet (bulk)
    - finance allocation only for credit-holders
    """
    _ = min_pct  # always use settings via student_tuition_eligible
    settings = RegistrationSettings.get_settings()
    if settings.skip_tuition_check:
        logger.warning(
            "tuition_pct filter: skip_tuition_check=True — treating all as met"
        )
        return qs if met else qs.none()

    threshold = float(settings.min_tuition_payment_percentage or 0)
    credit_q = _has_tuition_credit_q()
    with_credit = qs.filter(credit_q)
    without_credit = qs.exclude(credit_q)

    if met:
        if threshold <= 0:
            candidates = qs
        else:
            # Commitment-only students with a completed payment row are in with_credit;
            # live eligibility still rejects them when there is no tuition schedule.
            candidates = with_credit
        return _live_filter_ids(candidates, want_met=True)

    # Below threshold: no credit + credit-holders who fail eligibility
    no_credit_ids = list(without_credit.values_list("id", flat=True))
    below_ids = _live_eval_ids(with_credit, want_met=False)
    combined = list({*no_credit_ids, *below_ids})
    if not combined:
        return qs.none()
    return qs.filter(id__in=combined)


def _live_filter_ids(candidates, *, want_met: bool):
    ids = _live_eval_ids(candidates, want_met=want_met)
    if not ids:
        return candidates.none()
    return candidates.filter(id__in=ids)


def _live_eval_ids(candidates, *, want_met: bool) -> list[int]:
    """
    Run live eligibility checks; return matching primary keys.

    Avoid QuerySet.iterator() — it uses PostgreSQL server-side cursors, which
    break behind PgBouncer (transaction pooling) with InvalidCursorName.
    """
    from admissions.models import AdmittedStudent

    select_related = (
        "application",
        "admitted_program",
        "admitted_batch",
        "intended_program_batch",
        "programme_enrollment__program_batch",
    )
    # Materialize ids on a normal query (no server-side cursor), then hydrate in chunks.
    candidate_ids = list(candidates.order_by("id").values_list("id", flat=True))
    matched: list[int] = []
    scanned = 0
    chunk_size = 40

    for i in range(0, len(candidate_ids), chunk_size):
        chunk = candidate_ids[i : i + chunk_size]
        students = (
            AdmittedStudent.objects.filter(id__in=chunk)
            .select_related(*select_related)
            .order_by("id")
        )
        for student in students:
            scanned += 1
            meets = student_meets_tuition_pct(student)
            if meets == bool(want_met):
                matched.append(student.id)

    logger.info(
        "tuition_pct live filter scanned=%s matched=%s want_met=%s threshold=%s",
        scanned,
        len(matched),
        want_met,
        registration_min_tuition_pct(),
    )
    return matched

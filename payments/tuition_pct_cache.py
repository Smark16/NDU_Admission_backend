"""Maintain AdmittedStudent.registration_tuition_pct_met for fast list filters."""
from __future__ import annotations

import logging
from typing import Iterable

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

logger = logging.getLogger(__name__)


def _has_tuition_credit_q() -> Q:
    """Portal/ledger tuition credit only (commitment flag alone is not enough)."""
    from payments.models import StudentTuitionPayment, TuitionLedger

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


def compute_registration_tuition_pct_met(student, min_pct: float | None = None) -> bool:
    """Same gate as registration eligibility / student_meets_tuition_pct."""
    from payments.tuition_pct_queryset import student_meets_tuition_pct

    return bool(student_meets_tuition_pct(student, min_pct))


def refresh_student_tuition_pct_cache(student, *, min_pct: float | None = None) -> bool:
    """Recompute and persist the cache flag for one student. Returns meets."""
    from admissions.models import AdmittedStudent

    meets = compute_registration_tuition_pct_met(student, min_pct=min_pct)
    AdmittedStudent.objects.filter(pk=student.pk).update(
        registration_tuition_pct_met=meets,
        registration_tuition_pct_at=timezone.now(),
    )
    student.registration_tuition_pct_met = meets
    student.registration_tuition_pct_at = timezone.now()
    return meets


def refresh_students_tuition_pct_cache(
    student_ids: Iterable[int],
    *,
    min_pct: float | None = None,
) -> dict:
    """Recompute cache for explicit student ids (one finance eval each)."""
    from admissions.models import AdmittedStudent

    ids = [int(i) for i in student_ids if i is not None]
    if not ids:
        return {"scanned": 0, "met": 0, "unmet": 0}

    scanned = met = unmet = 0
    select_related = (
        "application",
        "admitted_program",
        "admitted_batch",
        "intended_program_batch",
        "programme_enrollment__program_batch",
    )
    now = timezone.now()
    # Chunked loads — no QuerySet.iterator() (breaks behind PgBouncer).
    chunk_size = 40
    for i in range(0, len(ids), chunk_size):
        chunk = ids[i : i + chunk_size]
        students = (
            AdmittedStudent.objects.filter(id__in=chunk)
            .select_related(*select_related)
            .order_by("id")
        )
        for student in students:
            scanned += 1
            try:
                meets = compute_registration_tuition_pct_met(student, min_pct=min_pct)
            except Exception:
                logger.exception(
                    "tuition %% cache refresh failed for student id=%s", student.pk
                )
                meets = False
            AdmittedStudent.objects.filter(pk=student.pk).update(
                registration_tuition_pct_met=meets,
                registration_tuition_pct_at=now,
            )
            if meets:
                met += 1
            else:
                unmet += 1
    return {"scanned": scanned, "met": met, "unmet": unmet}


def mark_no_payment_activity_as_unmet(qs: QuerySet | None = None) -> int:
    """
    Students with no portal/ledger credit cannot meet the tuition % gate.
    Bulk-stamp them False without running finance allocation.
    """
    from admissions.models import AdmittedStudent

    base = qs if qs is not None else AdmittedStudent.objects.filter(
        is_admitted=True,
        admission_fee_paid=True,
    )
    to_stamp = base.filter(registration_tuition_pct_at__isnull=True).exclude(
        _has_tuition_credit_q()
    )
    return to_stamp.update(
        registration_tuition_pct_met=False,
        registration_tuition_pct_at=timezone.now(),
    )


def ensure_tuition_pct_cache_for_queryset(
    qs: QuerySet,
    *,
    prefer_payment_activity: bool = True,
    max_sync: int = 250,
) -> dict:
    """
    Warm cache for uncached rows in ``qs``.

    - Bulk-marks no-activity students as unmet (cheap).
    - Sync-evaluates up to ``max_sync`` students with payment activity.
    - Enqueues Celery for any remaining uncached ids.
    """
    stamped = mark_no_payment_activity_as_unmet(qs)

    uncached = qs.filter(registration_tuition_pct_at__isnull=True)
    if prefer_payment_activity:
        warm_qs = uncached.filter(_has_tuition_credit_q())
    else:
        warm_qs = uncached

    sync_ids = list(warm_qs.order_by("id").values_list("id", flat=True)[:max_sync])
    sync_result = refresh_students_tuition_pct_cache(sync_ids) if sync_ids else {
        "scanned": 0,
        "met": 0,
        "unmet": 0,
    }

    remaining = list(
        qs.filter(registration_tuition_pct_at__isnull=True)
        .order_by("id")
        .values_list("id", flat=True)[:8000]
    )
    queued = 0
    if remaining:
        try:
            from payments.tasks import celery_refresh_tuition_pct_cache

            chunk = 500
            for i in range(0, len(remaining), chunk):
                celery_refresh_tuition_pct_cache.delay(remaining[i : i + chunk])
                queued += len(remaining[i : i + chunk])
        except Exception:
            logger.exception("failed to enqueue tuition %% cache refresh")
            # Last resort: sync a bit more so filters are not empty forever.
            extra = remaining[:max_sync]
            extra_result = refresh_students_tuition_pct_cache(extra)
            sync_result = {
                "scanned": sync_result["scanned"] + extra_result["scanned"],
                "met": sync_result["met"] + extra_result["met"],
                "unmet": sync_result["unmet"] + extra_result["unmet"],
            }

    return {
        "stamped_no_activity": stamped,
        "sync": sync_result,
        "queued": queued,
    }


def backfill_bonafide_tuition_pct_cache(
    *,
    batch_size: int = 200,
    max_students: int | None = None,
) -> dict:
    """Full backfill for bonafide (admitted + commitment-paid) students."""
    from admissions.models import AdmittedStudent

    qs = AdmittedStudent.objects.filter(
        is_admitted=True,
        admission_fee_paid=True,
    ).order_by("id")

    stamped = mark_no_payment_activity_as_unmet(qs)

    # Remaining uncached rows with tuition credit need a real finance eval.
    need = qs.filter(registration_tuition_pct_at__isnull=True).filter(
        _has_tuition_credit_q()
    )
    if max_students is not None:
        need_ids = list(need.values_list("id", flat=True)[:max_students])
    else:
        need_ids = list(need.values_list("id", flat=True))

    scanned = met = unmet = 0
    for i in range(0, len(need_ids), batch_size):
        chunk = need_ids[i : i + batch_size]
        result = refresh_students_tuition_pct_cache(chunk)
        scanned += result["scanned"]
        met += result["met"]
        unmet += result["unmet"]

    return {
        "stamped_no_activity": stamped,
        "scanned": scanned,
        "met": met,
        "unmet": unmet,
        "candidates": len(need_ids),
    }


def invalidate_all_tuition_pct_cache() -> int:
    """Clear timestamps so the next filter/backfill recomputes (e.g. settings change)."""
    from admissions.models import AdmittedStudent

    return AdmittedStudent.objects.filter(
        registration_tuition_pct_at__isnull=False
    ).update(registration_tuition_pct_at=None)

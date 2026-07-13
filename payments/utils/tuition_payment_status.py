"""Reconcile portal tuition STK (StudentTuitionPayment) with SchoolPay Check API."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from payments.models import StudentTuitionPayment
from payments.utils.schoolpay import SchoolPayClient

logger = logging.getLogger(__name__)

GATEWAY_FAILED_STATUSES = frozenset({"FAILED", "CANCELLED"})


def receipt_from_schoolpay_payload(data: dict | None) -> str:
    """Prefer numeric receiptReference; SchoolPay often puts a URL in receiptNumber."""
    if not data:
        return ""
    ref = (data.get("receiptReference") or "").strip()
    if ref and not ref.startswith("http"):
        return ref
    num = (data.get("receiptNumber") or "").strip()
    if num and not num.startswith("http"):
        return num
    return ref or num or ""


def mark_tuition_payment_completed(
    payment: StudentTuitionPayment,
    *,
    receipt_number: str | None = None,
    transaction_id: str | None = None,
    schoolpay_payload: dict | None = None,
) -> StudentTuitionPayment:
    """
    Mark a portal tuition payment completed and sync commitment / enrollment.
    Idempotent if already completed.
    """
    receipt = (receipt_number or "").strip()
    if not receipt and schoolpay_payload:
        receipt = receipt_from_schoolpay_payload(schoolpay_payload)
    tid = transaction_id
    if tid is None and schoolpay_payload:
        tid = schoolpay_payload.get("transactionId")

    with transaction.atomic():
        locked = (
            StudentTuitionPayment.objects.select_for_update()
            .select_related("student")
            .filter(pk=payment.pk)
            .first()
        )
        if locked is None:
            return payment

        update_fields = ["updated_at"]
        if locked.status != "completed":
            locked.status = "completed"
            locked.paid_at = timezone.now()
            update_fields.extend(["status", "paid_at"])

        if receipt and locked.receipt_number != receipt:
            locked.receipt_number = receipt
            update_fields.append("receipt_number")

        if tid and not locked.transaction_id:
            locked.transaction_id = str(tid)
            update_fields.append("transaction_id")
        elif tid and locked.transaction_id and locked.transaction_id.startswith("TUI-"):
            # Keep portal ext_ref in notes; store SchoolPay txn id when blank of real id
            if "SchoolPay transactionId" not in (locked.notes or ""):
                locked.notes = (
                    (locked.notes or "").strip()
                    + f"\nSchoolPay transactionId: {tid}"
                ).strip()
                update_fields.append("notes")

        locked.save(update_fields=list(dict.fromkeys(update_fields)))
        student = locked.student

    if student_id := getattr(student, "pk", None):
        _sync_commitment_and_enrollment(student_id)

    payment.refresh_from_db()
    return payment


def _sync_commitment_and_enrollment(student_id: int) -> None:
    from admissions.models import AdmittedStudent
    from payments.programme_enrollment_activation import (
        try_activate_programme_enrollment_after_payment,
    )
    from payments.student_portal_finance import commitment_payment_summary

    student = AdmittedStudent.objects.filter(pk=student_id).first()
    if student is None:
        return

    summary = commitment_payment_summary(student)
    if summary.get("commitment_met") and not student.admission_fee_paid:
        student.admission_fee_paid = True
        student.admission_fee_paid_at = timezone.now()
        student.save(
            update_fields=["admission_fee_paid", "admission_fee_paid_at", "updated_at"]
        )

    try_activate_programme_enrollment_after_payment(student)


def reconcile_pending_tuition_payment(
    payment: StudentTuitionPayment, client=None
) -> str:
    """
    Poll SchoolPay for one pending tuition payment.
    Returns: 'paid' | 'failed' | 'pending' | 'error'
    """
    if not payment.payment_reference:
        logger.warning(
            "StudentTuitionPayment %s has no payment_reference; cannot reconcile",
            payment.pk,
        )
        return "error"

    if payment.status == "completed":
        return "paid"
    if payment.status in ("failed", "cancelled"):
        return "failed"

    if client is None:
        client = SchoolPayClient()

    try:
        data = client.check_status(payment.payment_reference)
    except Exception:
        logger.exception(
            "SchoolPay status check failed for tuition payment %s",
            payment.payment_reference,
        )
        return "error"

    if data.get("returnCode") != 0:
        return "pending"

    gateway_status = (data.get("status") or "").upper()
    if gateway_status == "PAID":
        mark_tuition_payment_completed(payment, schoolpay_payload=data)
        return "paid"

    if gateway_status in GATEWAY_FAILED_STATUSES:
        StudentTuitionPayment.objects.filter(pk=payment.pk, status="pending").update(
            status="failed"
        )
        return "failed"

    return "pending"


def reconcile_stale_pending_tuition_payments(
    queryset=None,
    *,
    stale_minutes=10,
    client=None,
):
    """
    For pending tuition STK older than stale_minutes:
    1. Poll SchoolPay — mark completed if PAID.
    2. Mark failed if gateway reports FAILED/CANCELLED.
    3. Otherwise abandon (mark failed) so the student can initiate again.
    """
    cutoff = timezone.now() - timedelta(minutes=stale_minutes)
    qs = queryset
    if qs is None:
        qs = StudentTuitionPayment.objects.filter(
            status="pending",
            created_at__lt=cutoff,
        ).exclude(payment_reference="")
    else:
        qs = qs.filter(status="pending", created_at__lt=cutoff).exclude(
            payment_reference=""
        )

    if client is None:
        client = SchoolPayClient()

    results = {
        "paid": 0,
        "failed": 0,
        "cleared": 0,
        "still_pending": 0,
        "errors": 0,
    }

    for payment in qs.iterator():
        outcome = reconcile_pending_tuition_payment(payment, client=client)
        payment.refresh_from_db()

        if outcome == "paid" or payment.status == "completed":
            results["paid"] += 1
            continue
        if outcome == "failed" or payment.status == "failed":
            results["failed"] += 1
            continue
        if outcome == "error":
            # Do not abandon on API errors — retry next beat.
            results["errors"] += 1
            continue

        if payment.status != "pending":
            continue

        # Still pending at gateway after stale window — abandon so student can retry.
        StudentTuitionPayment.objects.filter(pk=payment.pk, status="pending").update(
            status="failed"
        )
        results["cleared"] += 1

    return results

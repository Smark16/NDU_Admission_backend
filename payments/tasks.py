from celery import shared_task
from django.apps import apps
from django.utils import timezone
from datetime import timedelta
from payments.models import ApplicationPayment

from payments.utils.Transaction_sync import (
    fetch_transactions_by_range, reconcile_transactions
)

@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_process_delayed_payments(self):
    expired_time = timezone.now() - timedelta(minutes=10)

    updated_count = ApplicationPayment.objects.filter(
        status='PENDING',
        created_at__lt=expired_time
    ).update(status='FAILED')

    return f"{updated_count} payments marked as FAILED"

# delete failed payments
@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_delete_failed_payments(self):
    expired_time = timezone.now() - timedelta(minutes=10)

    updated_count = ApplicationPayment.objects.filter(
        status='FAILED',
        created_at__lt=expired_time
    ).delete()

    return f"{updated_count} payments have been deleted"

# sync payments from schoolpay
@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=10,
    retry_kwargs={"max_retries": 5},
)
def celery_sync_schoolpay_transactions(self):
    today = timezone.now().date()

    from_date = (
        today - timedelta(days=3)
    ).strftime("%Y-%m-%d")

    to_date = today.strftime("%Y-%m-%d")

    data = fetch_transactions_by_range(
        from_date=from_date,
        to_date=to_date
    )

    total_synced = reconcile_transactions(data)

    return (
        f"{total_synced} transaction(s) synced"
    )


@shared_task(bind=True, max_retries=5, default_retry_delay=30)
def celery_send_commitment_fee_reminder(self, student_id, paid_ugx=None, balance_ugx=None):
    """Send one commitment-fee payment reminder email via Celery."""
    from payments.utils.commitment_reminder_email import send_commitment_fee_reminder

    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")
    try:
        student = AdmittedStudent.objects.select_related(
            "application",
            "admitted_program",
            "admitted_campus",
        ).get(pk=student_id)
    except AdmittedStudent.DoesNotExist:
        return {"ok": False, "reason": "not_found", "student_id": student_id}

    ok = send_commitment_fee_reminder(
        student,
        paid_ugx=paid_ugx,
        balance_ugx=balance_ugx,
    )
    if not ok:
        raise self.retry(exc=Exception(f"SendGrid failed for student {student_id}"))
    return {"ok": True, "student_id": student_id}


@shared_task(bind=True)
def celery_bulk_send_commitment_reminders(self, cohort=None):
    """
    Celery job: find admitted students with unmet commitment fee and email them.
    Returns sent/failed/skipped counts for the API success message.
    """
    from payments.admin_ledger_views import _apply_student_cohort_filters
    from payments.student_portal_finance import (
        COMMITMENT_FEE_THRESHOLD,
        commitment_payment_summary,
    )
    from payments.utils.commitment_reminder_email import send_commitment_fee_reminder

    cohort = cohort or {}
    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")

    qs = (
        AdmittedStudent.objects.filter(is_admitted=True)
        .select_related(
            "application",
            "admitted_program",
            "admitted_campus",
            "admitted_batch",
        )
        .order_by("student_id")
    )
    qs = _apply_student_cohort_filters(qs, cohort)

    sent = 0
    failed = 0
    skipped_met = 0
    skipped_no_email = 0
    eligible = 0

    for student in qs.iterator(chunk_size=100):
        summary = commitment_payment_summary(student)
        if bool(summary["commitment_met"]):
            skipped_met += 1
            continue

        email = (getattr(student, "email", None) or "").strip()
        if not email:
            skipped_no_email += 1
            continue

        eligible += 1
        try:
            ok = send_commitment_fee_reminder(
                student,
                paid_ugx=float(summary["commitment_paid_ugx"]),
                balance_ugx=float(summary["commitment_balance"]),
            )
            if ok:
                sent += 1
            else:
                # Queue a retried single-send task so transient SendGrid errors recover
                celery_send_commitment_fee_reminder.delay(
                    student.id,
                    float(summary["commitment_paid_ugx"]),
                    float(summary["commitment_balance"]),
                )
                failed += 1
        except Exception:
            celery_send_commitment_fee_reminder.delay(
                student.id,
                float(summary["commitment_paid_ugx"]),
                float(summary["commitment_balance"]),
            )
            failed += 1

    return {
        "sent": sent,
        "failed": failed,
        "eligible": eligible,
        "skipped_met": skipped_met,
        "skipped_no_email": skipped_no_email,
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "filters": cohort,
    }

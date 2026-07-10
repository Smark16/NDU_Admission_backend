from celery import shared_task
from django.apps import apps
from django.utils import timezone
from datetime import timedelta
from payments.models import ApplicationPayment

from payments.utils.Transaction_sync import (
    fetch_transactions_by_range, reconcile_transactions
)
from payments.utils.application_payment_status import (
    reconcile_stale_pending_application_payments,
)

import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_process_delayed_payments(self):
    """
    Reconcile PENDING application-fee payments older than 10 minutes with SchoolPay.
    Auto-clears abandoned initiations (no PIN entered) so applicants can retry.
    """
    results = reconcile_stale_pending_application_payments()
    return (
        f"{results['paid']} paid, {results['failed']} failed, "
        f"{results['cleared']} cleared, {results['still_pending']} still pending, "
        f"{results['errors']} errors"
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_delete_failed_payments(self):
    """
    Disabled: failed application payments are kept for finance reconciliation.
    """
    logger.info(
        "auto_delete_failed_payments skipped (retention enabled for reconciliation)"
    )
    return "0 payments deleted (task disabled)"


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


def run_bulk_commitment_reminders(cohort=None):
    """
    Find admitted students with unmet commitment fee and email them.

    Do NOT use QuerySet.iterator() here: commitment_payment_summary() runs nested
    queries per student, which closes PostgreSQL server-side cursors and raises
    "cursor ... does not exist".
    """
    from payments.admin_ledger_views import _apply_student_cohort_filters
    from payments.student_portal_finance import (
        COMMITMENT_FEE_THRESHOLD,
        commitment_payment_summary,
    )
    from payments.utils.commitment_reminder_email import send_commitment_fee_reminder

    cohort = cohort or {}
    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")
    chunk_size = 100

    base_qs = AdmittedStudent.objects.filter(is_admitted=True).order_by("id")
    base_qs = _apply_student_cohort_filters(base_qs, cohort)
    student_ids = list(base_qs.values_list("id", flat=True))

    sent = 0
    failed = 0
    skipped_met = 0
    skipped_no_email = 0
    eligible = 0

    for offset in range(0, len(student_ids), chunk_size):
        chunk_ids = student_ids[offset : offset + chunk_size]
        students = (
            AdmittedStudent.objects.filter(id__in=chunk_ids)
            .select_related(
                "application",
                "admitted_program",
                "admitted_campus",
                "admitted_batch",
            )
            .order_by("id")
        )
        for student in students:
            summary = commitment_payment_summary(student)
            if bool(summary["commitment_met"]):
                skipped_met += 1
                continue

            email = (getattr(student, "email", None) or "").strip()
            if not email:
                skipped_no_email += 1
                continue

            eligible += 1
            paid_ugx = float(summary["commitment_paid_ugx"])
            balance_ugx = float(summary["commitment_balance"])
            try:
                ok = send_commitment_fee_reminder(
                    student,
                    paid_ugx=paid_ugx,
                    balance_ugx=balance_ugx,
                )
                if ok:
                    sent += 1
                else:
                    try:
                        celery_send_commitment_fee_reminder.delay(
                            student.id, paid_ugx, balance_ugx
                        )
                    except Exception:
                        logger.exception(
                            "Could not queue commitment reminder retry for student %s",
                            student.id,
                        )
                    failed += 1
            except Exception:
                logger.exception(
                    "Commitment reminder send failed for student %s", student.id
                )
                try:
                    celery_send_commitment_fee_reminder.delay(
                        student.id, paid_ugx, balance_ugx
                    )
                except Exception:
                    pass
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


@shared_task(bind=True)
def celery_bulk_send_commitment_reminders(self, cohort=None):
    """Celery wrapper around run_bulk_commitment_reminders (optional background use)."""
    return run_bulk_commitment_reminders(cohort)

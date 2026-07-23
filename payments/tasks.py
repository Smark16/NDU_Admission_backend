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
from payments.utils.tuition_payment_status import (
    reconcile_stale_pending_tuition_payments,
)

import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_process_delayed_payments(self):
    """
    Reconcile PENDING application-fee and portal tuition STK payments older than
    10 minutes with SchoolPay. Auto-clears abandoned initiations so payers can retry.
    """
    app = reconcile_stale_pending_application_payments()
    tuition = reconcile_stale_pending_tuition_payments()
    return (
        "application: "
        f"{app['paid']} paid, {app['failed']} failed, "
        f"{app['cleared']} cleared, {app['still_pending']} still pending, "
        f"{app['errors']} errors; "
        "tuition: "
        f"{tuition['paid']} paid, {tuition['failed']} failed, "
        f"{tuition['cleared']} cleared, {tuition['still_pending']} still pending, "
        f"{tuition['errors']} errors"
    )


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=10)
def auto_process_delayed_tuition_payments(self):
    """Reconcile stale pending StudentTuitionPayment rows with SchoolPay."""
    results = reconcile_stale_pending_tuition_payments()
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


def _unpaid_commitment_queryset(cohort=None):
    """Admitted students with unmet commitment fee and a usable email (DB-level filter)."""
    from payments.admin_ledger_views import _apply_student_cohort_filters
    from payments.commitment_queryset import filter_by_commitment_met

    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")
    qs = (
        AdmittedStudent.objects.filter(is_admitted=True)
        .exclude(application__email__isnull=True)
        .exclude(application__email="")
        .select_related("application")
    )
    qs = _apply_student_cohort_filters(qs, cohort or {})
    return filter_by_commitment_met(qs, False, strict=True)


def queue_bulk_commitment_reminders(cohort=None):
    """
    Fast path for the API: count eligible students and enqueue ONE Celery job.
    Does not send emails in the web request (avoids nginx/gunicorn timeouts).
    """
    from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD

    cohort = cohort or {}
    qs = _unpaid_commitment_queryset(cohort)
    queued = qs.count()

    if queued == 0:
        return {
            "status": "queued",
            "queued": 0,
            "sent": 0,
            "failed": 0,
            "eligible": 0,
            "skipped_met": 0,
            "skipped_no_email": 0,
            "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
            "filters": cohort,
            "task_id": None,
            "detail": "No admitted students with unpaid commitment fee matched the filters.",
        }

    async_result = celery_bulk_send_commitment_reminders.delay(cohort)
    return {
        "status": "queued",
        "queued": queued,
        "sent": queued,  # UI: number of notifications being sent
        "failed": 0,
        "eligible": queued,
        "skipped_met": 0,
        "skipped_no_email": 0,
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "filters": cohort,
        "task_id": async_result.id,
        "detail": (
            f"{queued} payment reminder(s) queued for background delivery "
            f"(commitment fee under UGX {int(COMMITMENT_FEE_THRESHOLD):,})."
        ),
    }


def run_bulk_commitment_reminders(cohort=None):
    """
    Worker-side send: DB-filter unpaid students, then email in chunks.
    Uses annotated paid amounts (no per-student finance allocation queries).
    """
    from decimal import Decimal
    import time

    from payments.commitment_queryset import annotate_commitment_ugx_paid
    from payments.student_payment_allocation import COMMITMENT_FEE_THRESHOLD
    from payments.utils.commitment_reminder_email import send_commitment_fee_reminder

    cohort = cohort or {}
    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")
    chunk_size = 100

    base_qs = _unpaid_commitment_queryset(cohort).order_by("id")
    student_ids = list(base_qs.values_list("id", flat=True))

    sent = 0
    failed = 0
    eligible = len(student_ids)

    for offset in range(0, len(student_ids), chunk_size):
        chunk_ids = student_ids[offset : offset + chunk_size]
        students = annotate_commitment_ugx_paid(
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
            email = (getattr(student, "email", None) or "").strip()
            if not email:
                failed += 1
                continue

            paid = Decimal(str(getattr(student, "commitment_paid_ugx", None) or 0))
            balance = max(COMMITMENT_FEE_THRESHOLD - paid, Decimal("0"))
            paid_ugx = float(paid)
            balance_ugx = float(balance)

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

        # Light pacing so large batches are gentler on SendGrid
        if offset + chunk_size < len(student_ids):
            time.sleep(0.25)

    return {
        "status": "completed",
        "sent": sent,
        "failed": failed,
        "eligible": eligible,
        "queued": eligible,
        "skipped_met": 0,
        "skipped_no_email": 0,
        "commitment_threshold": float(COMMITMENT_FEE_THRESHOLD),
        "filters": cohort,
    }


@shared_task(bind=True)
def celery_bulk_send_commitment_reminders(self, cohort=None):
    """Background job: send commitment reminders for unpaid admitted students."""
    return run_bulk_commitment_reminders(cohort)


@shared_task
def celery_send_bursar_weekly_report(triggered_by_user_id=None):
    from payments.bursar_weekly_send import send_bursar_weekly_report

    return send_bursar_weekly_report(triggered_by_user_id=triggered_by_user_id)


@shared_task
def celery_maybe_send_bursar_weekly_report():
    """Periodic check: send bursar PDF when schedule matches and not already sent this week."""
    from payments.bursar_weekly_send import send_bursar_weekly_report
    from payments.models import BursarWeeklyReportSettings

    settings_row = BursarWeeklyReportSettings.get_solo()
    if not settings_row.is_enabled:
        return {"skipped": "disabled"}

    now = timezone.localtime()
    if now.weekday() != settings_row.schedule_day:
        return {"skipped": "wrong_day"}
    if now.hour != settings_row.schedule_hour:
        return {"skipped": "wrong_hour"}
    if settings_row.schedule_minute and now.minute < settings_row.schedule_minute:
        return {"skipped": "too_early"}
    if settings_row.schedule_minute and now.minute > settings_row.schedule_minute + 20:
        return {"skipped": "too_late"}

    if settings_row.last_sent_at:
        last = timezone.localtime(settings_row.last_sent_at)
        if last.isocalendar()[:2] == now.isocalendar()[:2]:
            return {"skipped": "already_sent_this_week"}

    return send_bursar_weekly_report()

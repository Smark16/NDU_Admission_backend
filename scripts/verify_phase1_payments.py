"""
Local verification for Phase 1 application-fee payment fixes.
Usage: python manage.py shell < scripts/verify_phase1_payments.py
"""
import json
from decimal import Decimal
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import RequestFactory, override_settings
from django.utils import timezone

from Drafts.models import DraftApplication
from admissions.models import AcademicLevel, Application, Batch, Campus
from payments.models import ApplicationPayment
from payments.tasks import auto_delete_failed_payments, auto_process_delayed_payments
from payments.utils.application_payment_status import (
    mark_application_payment_paid,
    reconcile_pending_application_payment,
    reconcile_stale_pending_application_payments,
    schoolpay_application_fee_callback_url,
)
from payments.views import schoolpay_webhook

User = get_user_model()
PASS = 0
FAIL = 0


def ok(name):
    global PASS
    PASS += 1
    print(f"  OK  {name}")


def fail(name, detail=""):
    global FAIL
    FAIL += 1
    print(f" FAIL {name}" + (f" — {detail}" if detail else ""))


print("\n=== Phase 1 payment verification (local) ===\n")

# 1. Imports & Django check
try:
    from payments.utils import application_payment_status  # noqa: F401
    ok("module imports")
except Exception as exc:
    fail("module imports", str(exc))

with override_settings(BACKEND_URL="http://127.0.0.1:8000"):
    url = schoolpay_application_fee_callback_url()
    if url == "http://127.0.0.1:8000/api/payments/webhook/":
        ok("callback URL uses BACKEND_URL")
    else:
        fail("callback URL uses BACKEND_URL", url)

# 2. Isolated DB tests (rolled back — no permanent changes)
try:
    with transaction.atomic():
        user = User.objects.create_user(
            username=f"phase1verify_{timezone.now().timestamp()}@test.local",
            email=f"phase1verify_{timezone.now().timestamp()}@test.local",
            password="unused",
        )
        campus = Campus.objects.create(
            name=f"Verify Campus {timezone.now().timestamp()}",
            code=f"VC{int(timezone.now().timestamp()) % 100000}",
        )
        today = timezone.now().date()
        batch = Batch.objects.create(
            name="Phase1 Verify Batch",
            code=f"P1V{int(timezone.now().timestamp()) % 100000}",
            application_start_date=today,
            application_end_date=today + timedelta(days=30),
            admission_start_date=today,
            admission_end_date=today + timedelta(days=60),
            created_by=user,
        )
        level = AcademicLevel.objects.create(
            name=f"Verify Level {int(timezone.now().timestamp()) % 100000}"
        )
        draft = DraftApplication.objects.create(
            applicant=user,
            batch=batch,
            application_fee_paid=False,
        )
        ext_ref = f"APP-VERIFY{int(timezone.now().timestamp())}"
        payment = ApplicationPayment.objects.create(
            user=user,
            external_reference=ext_ref,
            payment_reference=f"SP-VERIFY-{int(timezone.now().timestamp())}",
            amount=Decimal("50000.00"),
            phone_number="256700000000",
            status="PENDING",
        )
        ApplicationPayment.objects.filter(pk=payment.pk).update(
            created_at=timezone.now() - timedelta(minutes=15)
        )
        payment.refresh_from_db()

        mock_client = MagicMock()
        mock_client.check_status.return_value = {
            "returnCode": 0,
            "status": "PAID",
            "receiptNumber": "RCPT-VERIFY",
            "transactionId": "TXN-VERIFY",
        }
        outcome = reconcile_pending_application_payment(payment, client=mock_client)
        payment.refresh_from_db()
        draft.refresh_from_db()
        if outcome == "paid" and payment.status == "PAID" and draft.application_fee_paid:
            ok("reconcile marks PAID from gateway (mock)")
        else:
            fail("reconcile marks PAID from gateway (mock)", f"outcome={outcome}")

        application = Application.objects.create(
            applicant=user,
            batch=batch,
            campus=campus,
            academic_level=level,
            first_name="Verify",
            last_name="User",
            date_of_birth="2000-01-01",
            gender="male",
            nationality="Ugandan",
            phone="256700000000",
            email=user.email,
            next_of_kin_name="Kin",
            next_of_kin_contact="256700000001",
            next_of_kin_relationship="Parent",
            application_reference=ext_ref,
            application_fee_paid=False,
            status="submitted",
        )
        payment.status = "PAID"
        payment.save(update_fields=["status"])

        request = RequestFactory().post(
            "/api/payments/webhook/",
            data=json.dumps(
                {
                    "status": "PAID",
                    "paymentReference": payment.payment_reference,
                    "receiptNumber": "RCPT-WH-VERIFY",
                    "transactionId": "TXN-WH-VERIFY",
                }
            ),
            content_type="application/json",
        )
        response = schoolpay_webhook(request)
        application.refresh_from_db()
        payment.refresh_from_db()
        if response.status_code == 200 and application.application_fee_paid:
            ok("webhook duplicate heals unpaid application")
        else:
            fail(
                "webhook duplicate heals unpaid application",
                f"status={response.status_code} fee_paid={application.application_fee_paid}",
            )

        mock_client.check_status.return_value = {"returnCode": 0, "status": "PENDING"}
        payment.status = "PENDING"
        payment.save(update_fields=["status"])
        outcome = reconcile_pending_application_payment(payment, client=mock_client)
        payment.refresh_from_db()
        if outcome == "pending" and payment.status == "PENDING":
            ok("reconcile does not blind-fail when gateway pending")
        else:
            fail("reconcile does not blind-fail when gateway pending")

        transaction.set_rollback(True)
except Exception as exc:
    fail("isolated DB scenario", str(exc))
    import traceback
    traceback.print_exc()

# 3. Celery task wiring
try:
    with patch(
        "payments.tasks.reconcile_stale_pending_application_payments",
        return_value={"paid": 0, "failed": 0, "still_pending": 0, "errors": 0},
    ) as mocked:
        result = auto_process_delayed_payments()
        if mocked.called and "still pending" in result:
            ok("celery delayed task calls reconcile helper")
        else:
            fail("celery delayed task calls reconcile helper", result)

    before = ApplicationPayment.objects.count()
    result = auto_delete_failed_payments()
    after = ApplicationPayment.objects.count()
    if before == after and "disabled" in result:
        ok("celery delete task disabled (no row deletion)")
    else:
        fail("celery delete task disabled", result)
except Exception as exc:
    fail("celery task wiring", str(exc))

# 4. Beat schedule — auto_delete removed
try:
    from django.conf import settings

    beat = settings.CELERY_BEAT_SCHEDULE
    if "process_failed_payments" not in beat:
        ok("beat schedule no longer deletes failed payments")
    else:
        fail("beat schedule still schedules payment deletion")
except Exception as exc:
    fail("beat schedule check", str(exc))

# 5. Webhook route smoke (RequestFactory — no ALLOWED_HOSTS issues)
try:
    request = RequestFactory().post(
        "/api/payments/webhook/",
        data=json.dumps({"status": "PAID"}),
        content_type="application/json",
    )
    response = schoolpay_webhook(request)
    if response.status_code == 200 and b"ignored" in response.content:
        ok("webhook route responds (missing ref ignored)")
    else:
        fail(
            "webhook route responds",
            f"status={response.status_code} body={response.content[:120]!r}",
        )
except Exception as exc:
    fail("webhook route responds", str(exc))

print(f"\n=== Results: {PASS} passed, {FAIL} failed ===\n")
if FAIL:
    raise SystemExit(1)

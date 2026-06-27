import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone
from datetime import timedelta

from Drafts.models import DraftApplication
from admissions.models import AcademicLevel, Application, Batch, Campus
from payments.models import ApplicationPayment
from payments.tasks import auto_delete_failed_payments, auto_process_delayed_payments
from payments.utils.application_payment_status import (
    mark_application_payment_paid,
    reconcile_pending_application_payment,
    reconcile_stale_pending_application_payments,
    schoolpay_application_fee_callback_url,
    sync_draft_and_application_on_paid,
)
from payments.views import schoolpay_webhook

User = get_user_model()


class ApplicationPaymentStatusTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="paytest@example.com",
            email="paytest@example.com",
            password="testpass123",
        )
        self.campus = Campus.objects.create(name="Main Campus", code="MAIN")
        today = timezone.now().date()
        self.batch = Batch.objects.create(
            name="Test Intake 2026",
            code="TEST2026",
            application_start_date=today,
            application_end_date=today + timedelta(days=90),
            admission_start_date=today,
            admission_end_date=today + timedelta(days=120),
            created_by=self.user,
        )
        self.level = AcademicLevel.objects.create(name="Undergraduate")
        self.draft = DraftApplication.objects.create(
            applicant=self.user,
            batch=self.batch,
            application_fee_paid=False,
        )
        self.ext_ref = "APP-TESTREF123"
        self.payment = ApplicationPayment.objects.create(
            user=self.user,
            external_reference=self.ext_ref,
            payment_reference="SP-REF-001",
            amount=Decimal("50000.00"),
            phone_number="256700000000",
            status="PENDING",
        )
        # Backdate so stale reconciliation picks it up
        ApplicationPayment.objects.filter(pk=self.payment.pk).update(
            created_at=timezone.now() - timedelta(minutes=15)
        )
        self.payment.refresh_from_db()

    def test_callback_url_uses_backend_url(self):
        with override_settings(BACKEND_URL="http://127.0.0.1:8000"):
            url = schoolpay_application_fee_callback_url()
            self.assertEqual(url, "http://127.0.0.1:8000/api/payments/webhook/")

    def test_callback_url_falls_back_to_request(self):
        with override_settings(BACKEND_URL=""):
            request = RequestFactory().post("/api/payments/initiate_payment/")
            url = schoolpay_application_fee_callback_url(request)
            self.assertTrue(url.endswith("/api/payments/webhook/"))

    def test_mark_paid_updates_draft(self):
        mark_application_payment_paid(
            self.payment,
            receipt_number="RCPT-1",
            transaction_id="TXN-1",
            draft=self.draft,
        )
        self.payment.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(self.payment.status, "PAID")
        self.assertEqual(self.payment.receipt_number, "RCPT-1")
        self.assertTrue(self.draft.application_fee_paid)
        self.assertEqual(self.draft.application_reference, self.ext_ref)

    def test_mark_paid_heals_unpaid_application_by_reference(self):
        application = Application.objects.create(
            applicant=self.user,
            batch=self.batch,
            campus=self.campus,
            academic_level=self.level,
            first_name="Test",
            last_name="Applicant",
            date_of_birth="2000-01-01",
            gender="male",
            nationality="Ugandan",
            phone="256700000000",
            email="paytest@example.com",
            next_of_kin_name="Kin",
            next_of_kin_contact="256700000001",
            next_of_kin_relationship="Parent",
            application_reference=self.ext_ref,
            application_fee_paid=False,
            status="submitted",
        )
        mark_application_payment_paid(self.payment, draft=self.draft)
        application.refresh_from_db()
        self.payment.refresh_from_db()
        self.assertTrue(application.application_fee_paid)
        self.assertEqual(application.application_fee_amount, Decimal("50000.00"))
        self.assertEqual(self.payment.application_id, application.id)

    def test_reconcile_marks_paid_from_gateway(self):
        mock_client = MagicMock()
        mock_client.check_status.return_value = {
            "returnCode": 0,
            "status": "PAID",
            "receiptNumber": "RCPT-GW",
            "transactionId": "TXN-GW",
        }
        outcome = reconcile_pending_application_payment(self.payment, client=mock_client)
        self.payment.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(outcome, "paid")
        self.assertEqual(self.payment.status, "PAID")
        self.assertTrue(self.draft.application_fee_paid)

    def test_reconcile_does_not_fail_when_gateway_still_pending(self):
        mock_client = MagicMock()
        mock_client.check_status.return_value = {
            "returnCode": 0,
            "status": "PENDING",
        }
        outcome = reconcile_pending_application_payment(self.payment, client=mock_client)
        self.payment.refresh_from_db()
        self.assertEqual(outcome, "pending")
        self.assertEqual(self.payment.status, "PENDING")

    def test_reconcile_fails_only_when_gateway_says_failed(self):
        mock_client = MagicMock()
        mock_client.check_status.return_value = {
            "returnCode": 0,
            "status": "FAILED",
        }
        outcome = reconcile_pending_application_payment(self.payment, client=mock_client)
        self.payment.refresh_from_db()
        self.assertEqual(outcome, "failed")
        self.assertEqual(self.payment.status, "FAILED")

    def test_stale_reconcile_batch_counts(self):
        mock_client = MagicMock()
        mock_client.check_status.return_value = {
            "returnCode": 0,
            "status": "PAID",
            "receiptNumber": "RCPT-BATCH",
            "transactionId": "TXN-BATCH",
        }
        results = reconcile_stale_pending_application_payments(client=mock_client)
        self.assertEqual(results["paid"], 1)
        self.assertEqual(results["failed"], 0)
        self.assertEqual(results["still_pending"], 0)

    def test_webhook_marks_payment_paid(self):
        request = RequestFactory().post(
            "/api/payments/webhook/",
            data=json.dumps(
                {
                    "status": "PAID",
                    "paymentReference": "SP-REF-001",
                    "receiptNumber": "RCPT-WH",
                    "transactionId": "TXN-WH",
                }
            ),
            content_type="application/json",
        )
        response = schoolpay_webhook(request)
        self.assertEqual(response.status_code, 200)
        self.payment.refresh_from_db()
        self.draft.refresh_from_db()
        self.assertEqual(self.payment.status, "PAID")
        self.assertTrue(self.draft.application_fee_paid)

    def test_webhook_duplicate_heals_application_sync(self):
        application = Application.objects.create(
            applicant=self.user,
            batch=self.batch,
            campus=self.campus,
            academic_level=self.level,
            first_name="Test",
            last_name="Applicant",
            date_of_birth="2000-01-01",
            gender="male",
            nationality="Ugandan",
            phone="256700000000",
            email="paytest@example.com",
            next_of_kin_name="Kin",
            next_of_kin_contact="256700000001",
            next_of_kin_relationship="Parent",
            application_reference=self.ext_ref,
            application_fee_paid=False,
            status="submitted",
        )
        self.payment.status = "PAID"
        self.payment.save(update_fields=["status"])

        request = RequestFactory().post(
            "/api/payments/webhook/",
            data=json.dumps(
                {
                    "status": "PAID",
                    "paymentReference": "SP-REF-001",
                    "receiptNumber": "RCPT-WH2",
                    "transactionId": "TXN-WH2",
                }
            ),
            content_type="application/json",
        )
        response = schoolpay_webhook(request)
        self.assertEqual(response.status_code, 200)
        application.refresh_from_db()
        self.assertTrue(application.application_fee_paid)

    @patch(
        "payments.tasks.reconcile_stale_pending_application_payments",
        return_value={"paid": 1, "failed": 0, "still_pending": 2, "errors": 0},
    )
    def test_celery_delayed_task_uses_reconcile(self, mock_reconcile):
        result = auto_process_delayed_payments()
        mock_reconcile.assert_called_once()
        self.assertIn("1 paid", result)

    def test_celery_delete_task_is_disabled(self):
        ApplicationPayment.objects.filter(pk=self.payment.pk).update(status="FAILED")
        before = ApplicationPayment.objects.count()
        result = auto_delete_failed_payments()
        after = ApplicationPayment.objects.count()
        self.assertEqual(before, after)
        self.assertIn("disabled", result)

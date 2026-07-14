from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from payments.tasks import auto_process_delayed_payments
from payments.utils.tuition_payment_status import (
    receipt_from_schoolpay_payload,
    reconcile_pending_tuition_payment,
)


class ReceiptFromSchoolPayTests(SimpleTestCase):
    def test_prefers_receipt_reference_over_url(self):
        self.assertEqual(
            receipt_from_schoolpay_payload(
                {
                    "receiptNumber": "https://schoolpay.co.ug/adi6pat",
                    "receiptReference": "57701268",
                }
            ),
            "57701268",
        )

    def test_falls_back_to_non_url_receipt_number(self):
        self.assertEqual(
            receipt_from_schoolpay_payload({"receiptNumber": "57701268"}),
            "57701268",
        )


class TuitionReconcileUnitTests(SimpleTestCase):
    @patch("payments.utils.tuition_payment_status.mark_tuition_payment_completed")
    def test_reconcile_paid_calls_mark_completed(self, mock_mark):
        payment = MagicMock()
        payment.pk = 1
        payment.payment_reference = "26ADTEST"
        payment.status = "pending"
        mock_client = MagicMock()
        mock_client.check_status.return_value = {
            "returnCode": 0,
            "status": "PAID",
            "receiptReference": "57701268",
        }
        outcome = reconcile_pending_tuition_payment(payment, client=mock_client)
        self.assertEqual(outcome, "paid")
        mock_mark.assert_called_once()
        _, kwargs = mock_mark.call_args
        self.assertEqual(kwargs["schoolpay_payload"]["receiptReference"], "57701268")

    @patch("payments.utils.tuition_payment_status.StudentTuitionPayment")
    def test_reconcile_failed_updates_status(self, mock_model):
        payment = MagicMock()
        payment.pk = 2
        payment.payment_reference = "26ADFAIL"
        payment.status = "pending"
        mock_client = MagicMock()
        mock_client.check_status.return_value = {
            "returnCode": 0,
            "status": "FAILED",
        }
        outcome = reconcile_pending_tuition_payment(payment, client=mock_client)
        self.assertEqual(outcome, "failed")
        mock_model.objects.filter.assert_called()

    @patch("payments.tasks.reconcile_stale_pending_tuition_payments")
    @patch("payments.tasks.reconcile_stale_pending_application_payments")
    def test_celery_task_runs_both(self, mock_app, mock_tui):
        mock_app.return_value = {
            "paid": 0,
            "failed": 0,
            "cleared": 0,
            "still_pending": 0,
            "errors": 0,
        }
        mock_tui.return_value = {
            "paid": 1,
            "failed": 0,
            "cleared": 0,
            "still_pending": 0,
            "errors": 0,
        }
        msg = auto_process_delayed_payments()
        self.assertIn("tuition: 1 paid", msg)
        mock_app.assert_called_once()
        mock_tui.assert_called_once()

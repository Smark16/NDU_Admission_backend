from decimal import Decimal
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from payments.models import TuitionLedger
from admissions.models import AdmittedStudent

import hashlib
import requests
from django.conf import settings
from payments.utils.schoolpay_auth import schoolpay_api_root

# request hash
def generate_request_hash(date):
    raw_string = (
        f"{settings.SCHOOLPAY_USERNAME}"
        f"{settings.SCHOOLPAY_PASSWORD}"
        f"{settings.SCHOOLPAY_SCHOOL_CODE}"
        f"{date}"
    )

    return hashlib.sha256(raw_string.encode()).hexdigest()


def fetch_transactions_by_date(date):
    """
    Fetch transactions from SchoolPay API.
    """

    request_hash = generate_request_hash(date)

    url = (
        f"{schoolpay_api_root()}/AndroidRS/SyncSchoolTransactions/"
        f"{settings.SCHOOL_PAY_CODE}/"
        f"{date}/"
        f"{request_hash}"
    )

    response = requests.get(url, timeout=60)

    response.raise_for_status()

    return response.json()


def reconcile_transactions(data):
    transactions = data.get("transactions", [])

    created_count = 0

    for tx in transactions:

        receipt_number = tx.get("schoolpayReceiptNumber")

        # Prevent duplicates
        exists = TuitionLedger.objects.filter(
            schoolpay_receipt_number=receipt_number
        ).exists()

        if exists:
            continue

        payment_code = tx.get("studentPaymentCode")

        student = AdmittedStudent.objects.filter(
            student_id=payment_code
        ).select_related('application', 'student_user', 'admitted_program', 
        'admitted_batch', 'admitted_campus').first()

        ledger = TuitionLedger.objects.create(
            user=student.student_user if student else None,
            student=student,
            amount=Decimal(tx.get("amount", 0)),
            payment_date_time=parse_datetime(
                tx.get("paymentDateAndTime")
            ),
            schoolpay_receipt_number=receipt_number,
            settlement_bank_code=tx.get(
                "settlementBankCode"
            ),
            source_channel_trans_detail=tx.get(
                "sourceChannelTransDetail"
            ),
            source_channel_transaction_id=tx.get(
                "sourceChannelTransactionId"
            ),
            source_payment_channel=tx.get(
                "sourcePaymentChannel"
            ),
            student_name=tx.get("studentName"),
            student_payment_code=payment_code,
            student_registration_number=tx.get(
                "studentRegistrationNumber"
            ),
            transaction_completion_status=tx.get(
                "transactionCompletionStatus"
            ),
            raw_response=tx,
            reconciled=False,
        )

        # RECONCILIATION LOGIC
        if (
            student
            and ledger.transaction_completion_status == "Completed"
            and ledger.amount >= Decimal("150000")
        ):

            student.admission_fee_paid = True
            student.admission_fee_paid_at = timezone.now()

            # optional
            # student.can_download_offer_letter = True

            student.save()

            ledger.reconciled = True
            ledger.save(update_fields=["reconciled"])

        created_count += 1

    return created_count
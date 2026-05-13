from decimal import Decimal
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from payments.models import TuitionLedger
from admissions.models import AdmittedStudent

import hashlib
import requests
from django.conf import settings
from payments.utils.schoolpay_auth import schoolpay_api_root

ADMISSION_FEE_AMOUNT = Decimal("150000")

# request hash
def generate_request_hash(date_string):

    raw_string = (
        f"{settings.SCHOOL_PAY_CODE}"
        f"{date_string}"
        f"{settings.SCHOOL_PAY_PASSWORD}"
    )

    return hashlib.md5(raw_string.encode()).hexdigest().upper()

def fetch_transactions_by_date(date_string):
    request_hash = generate_request_hash(
        date_string
    )

    url = (
        f"{schoolpay_api_root()}/"
        f"SyncSchoolTransactions/"
        f"{settings.SCHOOL_PAY_CODE}/"
        f"{date_string}/"
        f"{request_hash}"
    )

    response = requests.get(url, timeout=60)

    response.raise_for_status()

    return response.json()


def fetch_transactions_by_range(
    from_date,
    to_date
):
    request_hash = generate_request_hash(
        from_date
    )

    url = (
        f"{schoolpay_api_root()}/"
        f"SyncSchoolTransactions/"
        f"{settings.SCHOOL_PAY_CODE}/"
        f"{from_date}/"
        f"{to_date}/"
        f"{request_hash}"
    )

    response = requests.get(url, timeout=60)

    response.raise_for_status()

    return response.json()

# Reconcile transactions with our database
def reconcile_transactions(data):

    transactions = data.get(
        "transactions",
        []
    )

    created_count = 0

    for tx in transactions:

        receipt_number = tx.get(
            "schoolpayReceiptNumber"
        )

        payment_code = tx.get(
            "studentPaymentCode"
        )

        # FIND STUDENT
        student = (
            AdmittedStudent.objects
            .select_related("user")
            .filter(
                student_id=payment_code
            )
            .first()
        )

        # CREATE TRANSACTION SAFELY
        ledger, created = (
            TuitionLedger.objects.get_or_create(

                schoolpay_receipt_number=receipt_number,

                defaults={

                    "user":
                        student.student_user if student else None,

                    "student":
                        student,

                    "amount":
                        Decimal(
                            tx.get("amount", "0")
                        ),

                    "payment_date_time":
                        parse_datetime(
                            tx.get(
                                "paymentDateAndTime"
                            )
                        ),

                    "settlement_bank_code":
                        tx.get(
                            "settlementBankCode"
                        ),

                    "source_channel_trans_detail":
                        tx.get(
                            "sourceChannelTransDetail"
                        ),

                    "source_channel_transaction_id":
                        tx.get(
                            "sourceChannelTransactionId"
                        ),

                    "source_payment_channel":
                        tx.get(
                            "sourcePaymentChannel"
                        ),

                    "student_name":
                        tx.get(
                            "studentName"
                        ),

                    "student_payment_code":
                        payment_code,

                    "student_registration_number":
                        tx.get(
                            "studentRegistrationNumber"
                        ),

                    "transaction_completion_status":
                        tx.get(
                            "transactionCompletionStatus"
                        ),

                    "raw_response":
                        tx,
                }
            )
        )

        # ALREADY EXISTS
        if not created:
            continue

        # RECONCILIATION
        if (
            student
            and ledger.transaction_completion_status == "Completed"
            and ledger.amount >= ADMISSION_FEE_AMOUNT
        ):

            student.admission_fee_paid = True

            student.admission_fee_paid_at = (
                timezone.now()
            )

            student.save(
                update_fields=[
                    "admission_fee_paid",
                    "admission_fee_paid_at"
                ]
            )

            ledger.reconciled = True

            ledger.save(
                update_fields=["reconciled"]
            )

        created_count += 1

    return created_count
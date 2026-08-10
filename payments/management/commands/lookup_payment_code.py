"""Find admitted student + TuitionLedger rows for a SchoolPay payment code."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

from admissions.models import AdmittedStudent
from payments.models import TuitionLedger


class Command(BaseCommand):
    help = "Lookup student + ledger rows by SchoolPay payment code / student_id / reg_no."

    def add_arguments(self, parser):
        parser.add_argument("code", help="SchoolPay code, student_id, or reg_no")

    def handle(self, *args, **options):
        code = (options["code"] or "").strip()
        if not code:
            self.stderr.write("Provide a code.")
            return

        students = list(
            AdmittedStudent.objects.filter(
                Q(student_id__iexact=code)
                | Q(schoolpay_code__iexact=code)
                | Q(reg_no__iexact=code)
            ).values(
                "id",
                "student_id",
                "schoolpay_code",
                "reg_no",
                "admission_fee_paid",
                "application__first_name",
                "application__last_name",
            )[:20]
        )
        self.stdout.write(f"AdmittedStudent matches ({len(students)}):")
        for s in students:
            name = f"{s['application__first_name'] or ''} {s['application__last_name'] or ''}".strip()
            self.stdout.write(
                f"  pk={s['id']} name={name!r} student_id={s['student_id']!r} "
                f"schoolpay={s['schoolpay_code']!r} reg={s['reg_no']!r} "
                f"commitment_paid={s['admission_fee_paid']}"
            )
        if not students:
            self.stdout.write("  (none)")

        ledgers = list(
            TuitionLedger.objects.filter(
                Q(student_payment_code__iexact=code)
                | Q(student_registration_number__iexact=code)
            )
            .order_by("-id")
            .values(
                "id",
                "amount",
                "transaction_completion_status",
                "student_payment_code",
                "student_registration_number",
                "student_name",
                "student_id",
                "schoolpay_receipt_number",
                "created_at",
            )[:30]
        )
        total = (
            TuitionLedger.objects.filter(
                student_payment_code__iexact=code,
                transaction_completion_status="Completed",
            ).aggregate(t=Sum("amount"))["t"]
            or 0
        )
        self.stdout.write(f"\nTuitionLedger matches ({len(ledgers)}; completed total={total}):")
        for row in ledgers:
            self.stdout.write(
                f"  #{row['id']} {row['amount']} {row['transaction_completion_status']} "
                f"code={row['student_payment_code']!r} reg={row['student_registration_number']!r} "
                f"name={row['student_name']!r} student_fk={row['student_id']} "
                f"receipt={row['schoolpay_receipt_number']!r} at={row['created_at']}"
            )
        if not ledgers:
            self.stdout.write("  (none — payment not in ERP ledger yet)")

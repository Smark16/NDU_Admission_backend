"""Find admitted student + TuitionLedger rows for a SchoolPay payment code."""
from __future__ import annotations

from collections import OrderedDict

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

from admissions.models import AdmittedStudent
from payments.models import TuitionLedger


class Command(BaseCommand):
    help = (
        "Lookup student + ledger rows by SchoolPay payment code / student_id / reg_no. "
        "Prints original SchoolPay names stored on payments for that code."
    )

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
                "application__middle_name",
                "application__last_name",
            )[:20]
        )
        self.stdout.write(f"AdmittedStudent matches ({len(students)}):")
        for s in students:
            name = " ".join(
                part
                for part in (
                    s["application__first_name"] or "",
                    s["application__middle_name"] or "",
                    s["application__last_name"] or "",
                )
                if part
            ).strip()
            self.stdout.write(
                f"  pk={s['id']} name={name!r} student_id={s['student_id']!r} "
                f"schoolpay={s['schoolpay_code']!r} reg={s['reg_no']!r} "
                f"commitment_paid={s['admission_fee_paid']}"
            )
        if not students:
            self.stdout.write("  (none)")

        name_qs = (
            TuitionLedger.objects.filter(
                Q(student_payment_code__iexact=code)
                | Q(student_registration_number__iexact=code)
            )
            .exclude(student_name="")
            .order_by("payment_date_time", "id")
            .values("student_name", "payment_date_time", "student_registration_number")
        )
        by_name: OrderedDict[str, dict] = OrderedDict()
        for row in name_qs:
            label = (row["student_name"] or "").strip()
            if not label:
                continue
            bucket = by_name.setdefault(
                label,
                {
                    "count": 0,
                    "first": row["payment_date_time"],
                    "last": row["payment_date_time"],
                    "regs": set(),
                },
            )
            bucket["count"] += 1
            if row["payment_date_time"] and (
                bucket["first"] is None or row["payment_date_time"] < bucket["first"]
            ):
                bucket["first"] = row["payment_date_time"]
            if row["payment_date_time"] and (
                bucket["last"] is None or row["payment_date_time"] > bucket["last"]
            ):
                bucket["last"] = row["payment_date_time"]
            reg = (row["student_registration_number"] or "").strip()
            if reg:
                bucket["regs"].add(reg)

        self.stdout.write(
            f"\nNames SchoolPay sent on this pay code ({len(by_name)} distinct):"
        )
        if not by_name:
            self.stdout.write(
                "  (none in TuitionLedger — pull SchoolPay history first, or the "
                "code has never paid in this ERP)"
            )
        else:
            for label, bucket in by_name.items():
                regs = ", ".join(sorted(bucket["regs"])) or "—"
                self.stdout.write(
                    f"  {label!r}  payments={bucket['count']}  "
                    f"first={bucket['first']}  last={bucket['last']}  "
                    f"reg_nos={regs}"
                )
            if len(by_name) > 1:
                self.stdout.write(
                    "  NOTE: more than one name on this code — likely a reused "
                    "SchoolPay wallet. The first row is the earliest name we have."
                )

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

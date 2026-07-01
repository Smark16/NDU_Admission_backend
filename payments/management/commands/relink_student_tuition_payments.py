"""Re-link SchoolPay tuition payments after programme or reg-no changes."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from admissions.models import AdmittedStudent
from payments.student_portal_finance import commitment_payment_summary
from payments.utils.tuition_ledger_linking import (
    payment_codes_for_student,
    relink_tuition_ledgers_for_student,
    tuition_ledger_queryset_for_student,
)


class Command(BaseCommand):
    help = (
        "Re-attach orphan SchoolPay ledger rows to an admitted student and "
        "refresh commitment/admission-fee flags."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "lookup",
            nargs="?",
            help="student_id, schoolpay code, or reg_no (e.g. 1011816571 or 26/1/328/D/421)",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Re-link every admitted student (slow).",
        )

    def handle(self, *args, **options):
        lookup = (options.get("lookup") or "").strip()
        if not lookup and not options["all"]:
            self.stderr.write("Provide a lookup value or use --all.")
            return

        if options["all"]:
            qs = AdmittedStudent.objects.filter(is_admitted=True).order_by("id")
        else:
            qs = AdmittedStudent.objects.filter(
                Q(student_id__iexact=lookup)
                | Q(schoolpay_code__iexact=lookup)
                | Q(reg_no__iexact=lookup)
            )
            if not qs.exists():
                self.stderr.write(self.style.ERROR(f"No admitted student for: {lookup!r}"))
                return

        total_linked = 0
        for student in qs.iterator():
            before = commitment_payment_summary(student)
            linked = relink_tuition_ledgers_for_student(student)
            student.refresh_from_db(fields=["admission_fee_paid", "admission_fee_paid_at"])
            after = commitment_payment_summary(student)
            ledger_count = tuition_ledger_queryset_for_student(student).filter(
                transaction_completion_status="Completed"
            ).count()
            total_linked += linked
            self.stdout.write(
                f"{student.reg_no} | codes={sorted(payment_codes_for_student(student))} | "
                f"ledgers={ledger_count} | relinked={linked} | "
                f"commitment_paid {before['commitment_paid_ugx']} -> {after['commitment_paid_ugx']} | "
                f"met={after['commitment_met']}"
            )

        self.stdout.write(self.style.SUCCESS(f"Done. ledger_rows_relinked={total_linked}"))

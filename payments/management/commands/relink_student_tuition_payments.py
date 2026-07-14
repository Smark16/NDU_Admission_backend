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
        parser.add_argument(
            "--only-changes",
            action="store_true",
            help="With --all, print only students that were relinked or changed.",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="With --all, print every student (very long).",
        )

    def handle(self, *args, **options):
        lookup = (options.get("lookup") or "").strip()
        if not lookup and not options["all"]:
            self.stderr.write("Provide a lookup value or use --all.")
            return

        if options["all"]:
            student_ids = list(
                AdmittedStudent.objects.filter(is_admitted=True)
                .order_by("id")
                .values_list("id", flat=True)
            )
        else:
            student_ids = list(
                AdmittedStudent.objects.filter(
                    Q(student_id__iexact=lookup)
                    | Q(schoolpay_code__iexact=lookup)
                    | Q(reg_no__iexact=lookup)
                ).values_list("id", flat=True)
            )
            if not student_ids:
                self.stderr.write(self.style.ERROR(f"No admitted student for: {lookup!r}"))
                return

        only_changes = options["only_changes"] or (
            options["all"] and not options["verbose"]
        )
        total_linked = 0
        processed = 0

        for student_id in student_ids:
            student = (
                AdmittedStudent.objects.select_related("student_user")
                .filter(pk=student_id)
                .first()
            )
            if student is None:
                continue

            before = commitment_payment_summary(student)
            linked = relink_tuition_ledgers_for_student(student)
            student.refresh_from_db(fields=["admission_fee_paid", "admission_fee_paid_at"])
            after = commitment_payment_summary(student)
            processed += 1
            total_linked += linked

            commitment_changed = (
                before["commitment_paid_ugx"] != after["commitment_paid_ugx"]
                or before["commitment_met"] != after["commitment_met"]
            )
            if only_changes and linked == 0 and not commitment_changed:
                continue

            ledger_count = tuition_ledger_queryset_for_student(student).filter(
                transaction_completion_status="Completed"
            ).count()
            self.stdout.write(
                f"{student.reg_no} | codes={sorted(payment_codes_for_student(student))} | "
                f"ledgers={ledger_count} | relinked={linked} | "
                f"commitment_paid {before['commitment_paid_ugx']} -> {after['commitment_paid_ugx']} | "
                f"met={after['commitment_met']}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. students_processed={processed} ledger_rows_relinked={total_linked}"
            )
        )

"""
Re-open EXEMPTION_FORM bills that were auto-completed from SchoolPay/tuition
credit (no MoMo payment_reference) and never submitted to HOD.

50k goes back onto the pending form-fee bill; SchoolPay credit returns to tuition
on the next finance load.

Usage:
  python manage.py reopen_exemption_form_fees --dry-run
  python manage.py reopen_exemption_form_fees
  python manage.py reopen_exemption_form_fees --include-submitted
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from admissions.exemption_services import EXEMPTION_FORM_FEE_CODE
from admissions.models import AdmissionChangeRequest, AdmittedStudent
from payments.models import FeeHead, StudentTuitionPayment


class Command(BaseCommand):
    help = (
        "Reopen auto-settled exemption form-fee charges (no SchoolPay prompt). "
        "Default: only students who never submitted to HOD."
    )

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", type=str, default="", help="Limit to one student reg no")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--include-submitted",
            action="store_true",
            help="Also reopen fees for students who already submitted to HOD.",
        )

    def handle(self, *args, **options):
        fh = FeeHead.objects.filter(code=EXEMPTION_FORM_FEE_CODE).first()
        if not fh:
            self.stderr.write("EXEMPTION_FORM fee head not found.")
            return

        qs = StudentTuitionPayment.objects.filter(
            source="ad_hoc",
            fee_head=fh,
            status="completed",
        ).filter(Q(payment_reference="") | Q(payment_reference__isnull=True))
        qs = qs.exclude(payment_method="mobile_money")

        reg = (options.get("reg_no") or "").strip()
        if reg:
            student = AdmittedStudent.objects.filter(reg_no__iexact=reg).first()
            if not student:
                self.stderr.write(f"Student not found: {reg}")
                return
            qs = qs.filter(student=student)

        if not options.get("include_submitted"):
            submitted_ids = set(
                AdmissionChangeRequest.objects.filter(change_type="exemption").values_list(
                    "admitted_student_id", flat=True
                )
            )
            qs = qs.exclude(student_id__in=submitted_ids)

        charges = list(qs.select_related("student", "student__application"))
        self.stdout.write(f"Matches: {len(charges)}")
        for charge in charges:
            student = charge.student
            try:
                name = student.full_name if student else ""
            except Exception:
                name = ""
            ref = (charge.payment_reference or "").strip() or "-"
            self.stdout.write(
                f"  charge={charge.id} {getattr(student, 'reg_no', '')} {name} "
                f"{charge.amount} method={charge.payment_method or '-'} ref={ref}"
            )

        if options["dry_run"]:
            self.stdout.write("Dry run — no changes.")
            return

        ids = [c.id for c in charges]
        n = StudentTuitionPayment.objects.filter(pk__in=ids).update(
            status="pending",
            paid_at=None,
            payment_reference="",
            payment_method="",
            transaction_id=None,
        )
        AdmissionChangeRequest.objects.filter(
            change_type="exemption",
            form_fee_charge_id__in=ids,
        ).update(form_fee_paid_at=None)
        self.stdout.write(self.style.SUCCESS(f"Reopened {n} exemption form-fee charge(s)."))
        self.stdout.write(
            "SchoolPay credit will sit on tuition again the next time finance loads. "
            "Students must pay the 50k with Submit and Pay on Course Exemption."
        )

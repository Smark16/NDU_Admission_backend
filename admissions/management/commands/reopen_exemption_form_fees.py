"""
Re-open EXEMPTION_FORM bills that were marked completed without a SchoolPay
phone-prompt (payment_reference). Those were often auto-completed via general
ledger allocation and blocked the MoMo pay UI.

Usage:
  python manage.py reopen_exemption_form_fees
  python manage.py reopen_exemption_form_fees --reg-no 26/2/328/W/1331
  python manage.py reopen_exemption_form_fees --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q

from admissions.exemption_services import EXEMPTION_FORM_FEE_CODE
from admissions.models import AdmissionChangeRequest, AdmittedStudent
from payments.models import FeeHead, StudentTuitionPayment


class Command(BaseCommand):
    help = "Reopen exemption form-fee charges that were completed without STK payment_reference."

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", type=str, default="", help="Limit to one student reg no")
        parser.add_argument("--dry-run", action="store_true")

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

        reg = (options.get("reg_no") or "").strip()
        if reg:
            student = AdmittedStudent.objects.filter(reg_no__iexact=reg).first()
            if not student:
                self.stderr.write(f"Student not found: {reg}")
                return
            qs = qs.filter(student=student)

        rows = list(
            qs.select_related("student").values_list(
                "id", "student__reg_no", "student__full_name", "amount"
            )
        )
        self.stdout.write(f"Matches: {len(rows)}")
        for rid, rno, name, amt in rows:
            self.stdout.write(f"  charge={rid} {rno} {name} {amt}")

        if options["dry_run"]:
            self.stdout.write("Dry run — no changes.")
            return

        ids = [r[0] for r in rows]
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

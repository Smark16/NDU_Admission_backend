"""
Cancel pending EXEMPTION_FORM (50k) bills for students who never submitted
an exemption change request. These charges are created when someone opens
the exemption page; they should not sit on the student's balance.

Usage:
  python manage.py cancel_unapplied_exemption_form_fees --dry-run
  python manage.py cancel_unapplied_exemption_form_fees
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from admissions.exemption_services import ensure_exemption_fee_heads
from admissions.models import AdmissionChangeRequest
from payments.models import StudentTuitionPayment


class Command(BaseCommand):
    help = (
        "Cancel unpaid EXEMPTION_FORM charges for students who never applied "
        "for exemption."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--reg-no", type=str, default="")

    def handle(self, *args, **options):
        dry = bool(options["dry_run"])
        form_head, _ = ensure_exemption_fee_heads()
        applied_ids = set(
            AdmissionChangeRequest.objects.filter(change_type="exemption").values_list(
                "admitted_student_id", flat=True
            )
        )
        qs = StudentTuitionPayment.objects.filter(
            source="ad_hoc",
            fee_head=form_head,
            status="pending",
            is_waived=False,
        ).select_related("student")
        if options["reg_no"]:
            qs = qs.filter(student__reg_no=options["reg_no"].strip())

        to_cancel = [c for c in qs if c.student_id not in applied_ids]
        self.stdout.write(f"pending unapplied EXEMPTION_FORM charges: {len(to_cancel)}")
        for c in to_cancel:
            s = c.student
            self.stdout.write(
                f"  {s.pk if s else ''} {getattr(s, 'reg_no', '')} "
                f"{getattr(s, 'full_name', '')} charge={c.id} {c.amount}"
            )
        if dry:
            self.stdout.write(self.style.WARNING("Dry run — nothing cancelled."))
            return
        note = (
            "Cancelled: exemption form opened but never submitted. "
            f"{timezone.now().date().isoformat()}"
        )
        n = 0
        for c in to_cancel:
            extra = (c.notes or "").strip()
            c.status = "cancelled"
            c.notes = f"{extra}\n{note}".strip() if extra else note
            c.save(update_fields=["status", "notes", "updated_at"])
            n += 1
        self.stdout.write(self.style.SUCCESS(f"Cancelled {n} charge(s)."))

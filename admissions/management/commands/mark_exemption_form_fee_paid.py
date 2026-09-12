"""
Mark the UGX 50,000 exemption form fee as paid (desk / finance correction).

Use when SchoolPay student-code money hit tuition, or a MoMo receipt exists
but the portal still shows "submitted without paying".

Usage:
  python manage.py mark_exemption_form_fee_paid --student-id 1012326815
  python manage.py mark_exemption_form_fee_paid --reg-no "26/2/000/D/5668"
  python manage.py mark_exemption_form_fee_paid --student-id 1012326815 --dry-run
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from admissions.exemption_services import ensure_exemption_form_fee_access, student_has_paid_exemption_form_fee
from admissions.exemption_form_fee_payment import manually_complete_exemption_form_fee
from admissions.models import AdmittedStudent


def _find_student(*, reg_no: str = "", student_id: str = "") -> AdmittedStudent:
    reg_no = (reg_no or "").strip()
    student_id = (student_id or "").strip()
    if not reg_no and not student_id:
        raise CommandError("Provide --reg-no or --student-id.")

    qs = AdmittedStudent.objects.select_related("application")
    if student_id:
        student = qs.filter(student_id=student_id).first()
        if student:
            return student
    if reg_no:
        student = qs.filter(reg_no=reg_no).first() or qs.filter(student_id=reg_no).first()
        if student:
            return student
    raise CommandError(f"Student not found ({reg_no or student_id}).")


class Command(BaseCommand):
    help = (
        "Mark exemption form fee paid so HOD can approve "
        "(corrects SchoolPay→tuition mis-allocation or missing MoMo stamp)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--reg-no", default="")
        parser.add_argument("--student-id", default="")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        student = _find_student(
            reg_no=options.get("reg_no") or "",
            student_id=options.get("student_id") or "",
        )
        name = ""
        try:
            name = student.application.full_name or ""
        except Exception:
            pass

        if student_has_paid_exemption_form_fee(student):
            self.stdout.write(
                self.style.SUCCESS(
                    f"{name or 'Student'} ({student.reg_no}) — form fee already counts as paid."
                )
            )
            return

        access = ensure_exemption_form_fee_access(student)
        charge_id = access.get("charge_id")
        if not charge_id:
            if options["dry_run"]:
                self.stdout.write("Would create form-fee charge then mark paid.")
                return
            access = ensure_exemption_form_fee_access(student)
            charge_id = access.get("charge_id")

        from payments.models import StudentTuitionPayment

        charge = StudentTuitionPayment.objects.filter(pk=charge_id, student=student).first()
        if charge is None:
            raise CommandError("Could not load exemption form-fee charge.")

        if options["dry_run"]:
            self.stdout.write(
                f"[DRY-RUN] Would mark charge #{charge.pk} paid for "
                f"{name or student.reg_no} ({student.student_id})."
            )
            return

        manually_complete_exemption_form_fee(charge, actor=None)
        student.refresh_from_db()

        if student_has_paid_exemption_form_fee(student):
            self.stdout.write(
                self.style.SUCCESS(
                    f"Form fee marked paid for {name or 'student'} "
                    f"({student.reg_no}, charge #{charge.pk}). HOD can now approve papers."
                )
            )
        else:
            raise CommandError("Charge updated but student still shows unpaid — check payment row.")

"""
Re-activate student portal logins for people who paid the UGX 50,000
exemption form fee but have not submitted an exemption application.

The paid fee is kept. They can log in and submit from Course Exemption.

Usage:
  python manage.py reactivate_paid_unsubmitted_exemption_students --dry-run
  python manage.py reactivate_paid_unsubmitted_exemption_students
  python manage.py reactivate_paid_unsubmitted_exemption_students --reg-no 26/1/B/111/D/992
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.exemption_services import exemption_form_fee_report
from admissions.models import AdmittedStudent, StudentPortalAccountAction
from admissions.student_accounts import ensure_student_portal_account

REASON = (
    "Reactivated so the student can submit course exemption after paying the form fee."
)


class Command(BaseCommand):
    help = (
        "Activate portal accounts for students who paid the exemption form fee "
        "and have not submitted yet."
    )

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--reg-no",
            type=str,
            default="",
            help="Limit to one registration number.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        reg = (options.get("reg_no") or "").strip()
        rows = exemption_form_fee_report("paid_unsubmitted")
        seen = set()
        students = []
        for row in rows:
            pk = row.get("student_pk")
            if not pk or pk in seen:
                continue
            if reg and (row.get("reg_no") or "").strip().lower() != reg.lower():
                continue
            seen.add(pk)
            students.append(row)

        if not students:
            self.stdout.write(self.style.SUCCESS("No paid-unsubmitted exemption students found."))
            return

        self.stdout.write(
            f"{'[DRY-RUN] ' if dry else ''}{len(students)} student(s) paid and have not submitted:"
        )

        activated = 0
        already = 0
        provisioned = 0
        missing = 0

        for row in students:
            student = (
                AdmittedStudent.objects.filter(pk=row["student_pk"])
                .select_related("student_user", "application")
                .first()
            )
            if student is None:
                missing += 1
                self.stdout.write(self.style.WARNING(f"  skip missing pk={row['student_pk']}"))
                continue

            user = student.student_user
            name = row.get("student_name") or ""
            reg_no = row.get("reg_no") or student.reg_no or ""
            was_inactive = bool(user and not user.is_active)
            had_user = bool(user)

            if dry:
                state = "no login" if not user else ("inactive" if was_inactive else "already active")
                self.stdout.write(f"  {reg_no} {name} — {state} (fee kept)")
                continue

            with transaction.atomic():
                if user is None:
                    user, created = ensure_student_portal_account(student)
                    student.refresh_from_db(fields=["student_user_id"])
                    user = student.student_user or user
                    if created:
                        provisioned += 1
                    if user is None:
                        missing += 1
                        self.stdout.write(
                            self.style.WARNING(f"  {reg_no} {name} — could not create portal login")
                        )
                        continue

                fields = []
                if not user.is_active:
                    user.is_active = True
                    fields.append("is_active")
                if not user.is_student:
                    user.is_student = True
                    fields.append("is_student")
                if fields:
                    user.save(update_fields=fields)
                    StudentPortalAccountAction.objects.create(
                        student=student,
                        portal_user=user,
                        action=StudentPortalAccountAction.ACTION_ACTIVATE,
                        reason=REASON,
                        performed_by=None,
                    )
                    activated += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  {reg_no} {name} — portal activated (fee kept)")
                    )
                else:
                    already += 1
                    extra = " (new login created)" if not had_user else ""
                    self.stdout.write(f"  {reg_no} {name} — already active{extra} (fee kept)")

        if dry:
            self.stdout.write("Dry run — no accounts were changed. Re-run without --dry-run to activate.")
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Activated {activated}, already active {already}, "
                f"new logins {provisioned}, skipped {missing}."
            )
        )
        self.stdout.write(
            "Students keep the paid 50k form fee. They should log in and submit Course Exemption."
        )

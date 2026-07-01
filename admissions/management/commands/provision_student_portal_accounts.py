"""
Create or link ERP student portal accounts for admitted students.

Examples::

    # Create accounts + email credentials (recommended for missing accounts)
    python manage.py provision_student_portal_accounts --send-email

    # Preview only
    python manage.py provision_student_portal_accounts --dry-run

    # Resend credentials to students who already have accounts (no new provisioning)
    python manage.py provision_student_portal_accounts --email-only --all
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from admissions.models import AdmittedStudent
from admissions.student_accounts import (
    DEFAULT_STUDENT_PASSWORD,
    ensure_student_portal_account,
    student_portal_username,
)
from admissions.utils.email import send_student_login_credentials
from admissions.utils.student_portal_provisioning import (
    StudentPortalProvisioningError,
    auto_enroll_admitted_student,
    provision_student_portal_on_admission,
)


class Command(BaseCommand):
    help = "Create or link ERP student portal accounts for admitted students."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report missing accounts without creating or linking users.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Process every admitted student (default: only those missing student_user).",
        )
        parser.add_argument(
            "--email-only",
            action="store_true",
            help="Send login credential emails only (no account creation).",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Reset portal passwords to the default first-login password (NDU@1234).",
        )
        parser.add_argument(
            "--send-email",
            action="store_true",
            help="Email login credentials after each account is created in this run.",
        )
        parser.add_argument(
            "--admission-id",
            type=int,
            default=None,
            help="Provision a single AdmittedStudent by primary key.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max records to process (0 = no limit).",
        )

    def _send_credentials(self, admission, user) -> bool:
        sent = send_student_login_credentials(
            user,
            DEFAULT_STUDENT_PASSWORD,
            admission=admission,
        )
        address = (user.email or admission.application.email or "").strip()
        if sent:
            self.stdout.write(f"  Email sent to {address or '(no address)'}")
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  Credentials email failed for {address or 'no email on file'}"
                )
            )
        return sent

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        missing_only = not options["all"]
        email_only = options["email_only"]
        reset_password = options["reset_password"]
        send_email = options["send_email"]
        admission_id = options["admission_id"]
        limit = options["limit"]

        if email_only and dry_run:
            self.stderr.write("--email-only cannot be combined with --dry-run")
            return

        qs = (
            AdmittedStudent.objects.filter(is_admitted=True)
            .select_related("application__applicant", "student_user")
            .order_by("id")
        )
        if admission_id:
            qs = qs.filter(pk=admission_id)
        elif email_only:
            qs = qs.filter(student_user__isnull=False)
        elif missing_only:
            qs = qs.filter(student_user__isnull=True)

        if limit:
            qs = qs[:limit]

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.SUCCESS("No admitted students matched."))
            return

        mode = "email-only" if email_only else ("dry-run" if dry_run else "provision")
        self.stdout.write(f"[{mode}] Processing {total} admitted student(s)…\n")

        created = linked = skipped = failed = emailed = 0

        for admission in qs:
            reg_no = (admission.reg_no or "").strip()
            name = f"{admission.application.first_name} {admission.application.last_name}".strip()
            label = f"adm={admission.id} reg={reg_no or '—'} {name}"

            if email_only:
                user = admission.student_user
                if user is None:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"SKIP (no portal user): {label}"))
                    continue
                if self._send_credentials(admission, user):
                    emailed += 1
                    self.stdout.write(self.style.SUCCESS(f"EMAILED: {label}"))
                else:
                    failed += 1
                continue

            if not reg_no:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"SKIP (no reg_no): {label}"))
                continue

            if dry_run:
                username = student_portal_username(reg_no)
                if admission.student_user_id:
                    linked += 1
                    self.stdout.write(f"OK (already linked): {label} → {username}")
                else:
                    created += 1
                    self.stdout.write(
                        f"WOULD CREATE: {label} → username {username}"
                        + (" + email" if send_email else "")
                    )
                continue

            before_user_id = admission.student_user_id
            try:
                if reset_password and before_user_id:
                    user, was_created = ensure_student_portal_account(
                        admission, reset_password=True
                    )
                    auto_enroll_admitted_student(admission, admission.admitted_by_id)
                else:
                    provision_student_portal_on_admission(
                        admission.id,
                        send_credentials_email=False,
                    )
                    admission.refresh_from_db(fields=["student_user"])
                    user = admission.student_user
                    was_created = user is not None and before_user_id is None

                if user is None:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"SKIP (provision returned None): {label}"))
                    continue

                if was_created:
                    created += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"CREATED: {label} → {student_portal_username(reg_no)}"
                        )
                    )
                else:
                    linked += 1
                    self.stdout.write(f"LINKED (already had account): {label}")

                if send_email and was_created:
                    if self._send_credentials(admission, user):
                        emailed += 1

            except StudentPortalProvisioningError as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"FAIL: {label} — {exc}"))
            except Exception as exc:
                failed += 1
                self.stdout.write(self.style.ERROR(f"FAIL: {label} — {exc}"))

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Done. created={created} linked={linked} emailed={emailed} "
                f"skipped={skipped} failed={failed}"
            )
        )

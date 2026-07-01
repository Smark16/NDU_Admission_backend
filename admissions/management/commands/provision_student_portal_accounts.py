"""
Create or link ERP student portal accounts for admitted students.

Examples::

    # Reset passwords for students who have not accessed the ERP portal since admission
    python manage.py provision_student_portal_accounts --reset-password

    # Preview how many would be reset
    python manage.py provision_student_portal_accounts --dry-run --reset-password

    # Reset + email credentials to that same group
    python manage.py provision_student_portal_accounts --reset-password --send-email

    # Force reset ALL admitted students (including those who already logged in)
    python manage.py provision_student_portal_accounts --reset-password --all

    # Only students missing portal accounts
    python manage.py provision_student_portal_accounts --send-email
"""
from __future__ import annotations

from django.core.management.base import BaseCommand

from admissions.models import AdmittedStudent
from admissions.student_accounts import (
    DEFAULT_STUDENT_PASSWORD,
    ensure_student_portal_account,
    needs_student_portal_password_reset,
    student_has_post_admission_portal_access,
    student_portal_username,
)
from admissions.utils.email import send_student_login_credentials
from admissions.utils.student_portal_provisioning import (
    StudentPortalProvisioningError,
    assert_student_portal_ready,
    auto_enroll_admitted_student,
    provision_student_portal_on_admission,
)


class Command(BaseCommand):
    help = "Create, link, or reset ERP student portal accounts for admitted students."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report without making changes.",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Include every admitted student. With --reset-password, also resets students who already logged in.",
        )
        parser.add_argument(
            "--email-only",
            action="store_true",
            help="Send login credential emails only (no account changes).",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help=(
                "Reset passwords to NDU@1234 for students who have not accessed the "
                "ERP portal since admission. Use --all to include everyone."
            ),
        )
        parser.add_argument(
            "--send-email",
            action="store_true",
            help="Email login credentials after each successful update.",
        )
        parser.add_argument(
            "--admission-id",
            type=int,
            default=None,
            help="Single AdmittedStudent primary key.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max records (0 = no limit).",
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

    def _print_reset_eligibility_stats(self, qs) -> None:
        total = qs.count()
        missing_user = with_user = pre_admission_only = post_admission_active = eligible = 0
        for admission in qs.iterator():
            user = admission.student_user
            if user is None:
                missing_user += 1
                eligible += 1
                continue
            with_user += 1
            if student_has_post_admission_portal_access(admission):
                post_admission_active += 1
            else:
                pre_admission_only += 1
                eligible += 1

        self.stdout.write(f"  Total admitted: {total}")
        self.stdout.write(f"  No portal account: {missing_user}")
        self.stdout.write(f"  Portal account linked: {with_user}")
        self.stdout.write(f"  Logged in before admission only: {pre_admission_only}")
        self.stdout.write(
            f"  Logged in after admission (skipped): {post_admission_active}"
        )
        self.stdout.write(f"  Eligible for --reset-password: {eligible}")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        reset_password = options["reset_password"]
        include_all = options["all"]
        missing_only = not include_all and not reset_password
        email_only = options["email_only"]
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

        if reset_password and not include_all and not admission_id:
            eligible_ids = [
                admission.pk
                for admission in qs.iterator()
                if needs_student_portal_password_reset(admission)
            ]
            qs = (
                AdmittedStudent.objects.filter(pk__in=eligible_ids)
                .select_related("application__applicant", "student_user")
                .order_by("id")
            )

        if limit:
            qs = qs[:limit]

        total = qs.count()
        if total == 0:
            if reset_password and not include_all and not admission_id:
                self.stdout.write(
                    self.style.WARNING("No admitted students matched for password reset.")
                )
                base_qs = AdmittedStudent.objects.filter(is_admitted=True)
                self.stdout.write("Eligibility breakdown:")
                self._print_reset_eligibility_stats(base_qs)
            else:
                self.stdout.write(self.style.SUCCESS("No admitted students matched."))
            return

        if reset_password:
            scope = (
                "all admitted students"
                if include_all
                else "students without post-admission portal access"
            )
            self.stdout.write(
                self.style.WARNING(
                    f"Will reset portal passwords to {DEFAULT_STUDENT_PASSWORD} "
                    f"for {total} {scope}."
                )
            )

        mode = (
            "email-only"
            if email_only
            else ("dry-run" if dry_run else ("reset-password" if reset_password else "provision"))
        )
        self.stdout.write(f"[{mode}] Processing {total} admitted student(s)…\n")

        created = linked = reset = skipped = failed = emailed = skipped_logged_in = 0

        for admission in qs:
            reg_no = (admission.reg_no or "").strip()
            name = f"{admission.application.first_name} {admission.application.last_name}".strip()
            label = f"adm={admission.id} reg={reg_no or '—'} {name}"

            if (
                reset_password
                and not include_all
                and not needs_student_portal_password_reset(admission)
            ):
                skipped_logged_in += 1
                continue

            if email_only:
                user = admission.student_user
                if user is None:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"SKIP (no portal user): {label}"))
                    continue
                if dry_run:
                    self.stdout.write(f"WOULD EMAIL: {label}")
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
                if reset_password:
                    self.stdout.write(f"WOULD RESET PASSWORD: {label} → {username}")
                    reset += 1
                elif admission.student_user_id:
                    linked += 1
                    self.stdout.write(f"OK (already linked): {label} → {username}")
                else:
                    created += 1
                    self.stdout.write(f"WOULD CREATE: {label} → {username}")
                continue

            before_user_id = admission.student_user_id
            try:
                if reset_password:
                    user, was_created = ensure_student_portal_account(
                        admission, reset_password=True
                    )
                    auto_enroll_admitted_student(admission, admission.admitted_by_id)
                    assert_student_portal_ready(admission)
                    reset += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"RESET: {label} → {student_portal_username(reg_no)}"
                        )
                    )
                else:
                    provision_student_portal_on_admission(
                        admission.id,
                        send_credentials_email=False,
                    )
                    admission.refresh_from_db(fields=["student_user"])
                    user = admission.student_user
                    was_created = user is not None and before_user_id is None
                    if was_created:
                        created += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"CREATED: {label} → {student_portal_username(reg_no)}"
                            )
                        )
                    else:
                        linked += 1
                        self.stdout.write(f"LINKED: {label}")

                if send_email and user is not None:
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
                f"Done. created={created} linked={linked} reset={reset} "
                f"emailed={emailed} skipped={skipped} skipped_logged_in={skipped_logged_in} "
                f"failed={failed}"
            )
        )

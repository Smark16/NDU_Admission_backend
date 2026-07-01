"""
Audit admitted students for student-portal login readiness.

Examples::

    python manage.py audit_student_portal_accounts
    python manage.py audit_student_portal_accounts --fix
    python manage.py audit_student_portal_accounts --test-login --limit 10
"""
from __future__ import annotations

from django.contrib.auth import authenticate
from django.core.management.base import BaseCommand

from admissions.models import AdmittedStudent
from admissions.student_accounts import DEFAULT_STUDENT_PASSWORD, student_portal_username
from admissions.utils.student_portal_provisioning import (
    StudentPortalProvisioningError,
    assert_student_portal_ready,
    provision_student_portal_on_admission,
)


class Command(BaseCommand):
    help = "Verify admitted students can log in to the student portal."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Provision/repair missing or invalid portal accounts.",
        )
        parser.add_argument(
            "--test-login",
            action="store_true",
            help="Attempt authenticate() with reg no + default password.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Max records to test-login (0 = all).",
        )

    def handle(self, *args, **options):
        do_fix = options["fix"]
        test_login = options["test_login"]
        limit = options["limit"]

        qs = (
            AdmittedStudent.objects.filter(is_admitted=True)
            .select_related("student_user", "application")
            .order_by("id")
        )
        total = qs.count()
        ready = missing_user = invalid = fixed = login_ok = login_fail = 0
        problems: list[str] = []

        for admission in qs:
            reg_no = (admission.reg_no or "").strip()
            label = f"adm={admission.id} reg={reg_no or '—'}"

            try:
                if not reg_no:
                    invalid += 1
                    problems.append(f"NO_REG_NO {label}")
                    continue

                if not admission.student_user_id:
                    missing_user += 1
                    problems.append(f"NO_PORTAL_USER {label}")
                    if do_fix:
                        provision_student_portal_on_admission(
                            admission.id, send_credentials_email=False
                        )
                        admission.refresh_from_db(fields=["student_user"])
                        fixed += 1
                        self.stdout.write(self.style.SUCCESS(f"FIXED {label}"))
                    continue

                assert_student_portal_ready(admission)
                ready += 1

                if test_login and (not limit or login_ok + login_fail < limit):
                    user = authenticate(
                        username=reg_no,
                        password=DEFAULT_STUDENT_PASSWORD,
                    )
                    portal_user = authenticate(
                        username=student_portal_username(reg_no),
                        password=DEFAULT_STUDENT_PASSWORD,
                    )
                    if user or portal_user:
                        login_ok += 1
                    else:
                        login_fail += 1
                        problems.append(f"LOGIN_FAIL {label}")

            except StudentPortalProvisioningError as exc:
                invalid += 1
                problems.append(f"INVALID {label}: {exc}")
                if do_fix:
                    try:
                        provision_student_portal_on_admission(
                            admission.id, send_credentials_email=False
                        )
                        fixed += 1
                        self.stdout.write(self.style.SUCCESS(f"FIXED {label}"))
                    except StudentPortalProvisioningError as fix_exc:
                        self.stdout.write(self.style.ERROR(f"FIX FAILED {label}: {fix_exc}"))

        self.stdout.write("")
        self.stdout.write(f"Total admitted: {total}")
        self.stdout.write(self.style.SUCCESS(f"Portal ready: {ready}"))
        self.stdout.write(self.style.WARNING(f"Missing portal user: {missing_user}"))
        self.stdout.write(self.style.WARNING(f"Invalid / other issues: {invalid}"))
        if do_fix:
            self.stdout.write(self.style.SUCCESS(f"Fixed: {fixed}"))
        if test_login:
            self.stdout.write(f"Login test OK: {login_ok}")
            self.stdout.write(f"Login test failed: {login_fail}")

        if problems and not do_fix:
            self.stdout.write("\nFirst issues:")
            for line in problems[:20]:
                self.stdout.write(f"  {line}")
            if len(problems) > 20:
                self.stdout.write(f"  ... and {len(problems) - 20} more")

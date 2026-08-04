"""
Read-only audit: why admitted students might be getting 401 on ERP login.

Checks, for every is_admitted=True student:
  - Is a portal User linked at all?
  - Is that user active?
  - Is is_student=True (required to pass the ERP host's portal-kind gate in
    accounts/portal_login.py — applications-admin.ndu.ac.ug is an ERP host,
    and assert_user_allowed_on_portal() rejects with 401 if the account is
    not is_staff/is_student/is_lecturer/is_superuser)?
  - Does the username match the canonical reg_no-derived username?
  - Does the account have a usable password?
  - Has the account ever logged in?

Usage:
    python manage.py audit_student_portal_logins
    python manage.py audit_student_portal_logins --reg-no "26/1/301/D/904"
"""
from __future__ import annotations

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Audit admitted-student portal accounts for ERP login blockers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reg-no",
            default=None,
            help="Check a single student by registration number instead of scanning everyone.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=25,
            help="Max number of broken records to print per category (default 25).",
        )

    def handle(self, *args, **options):
        from admissions.models import AdmittedStudent
        from admissions.student_accounts import student_portal_username

        reg_no = options["reg_no"]
        limit = options["limit"]

        qs = AdmittedStudent.objects.filter(is_admitted=True).select_related(
            "student_user", "application"
        )
        if reg_no:
            qs = qs.filter(reg_no__iexact=reg_no.strip())

        total = qs.count()
        self.stdout.write(self.style.SUCCESS("=" * 78))
        self.stdout.write(self.style.SUCCESS(f"  STUDENT PORTAL LOGIN AUDIT  (admitted students: {total})"))
        self.stdout.write(self.style.SUCCESS("=" * 78))

        no_user = []
        inactive = []
        not_is_student = []
        bad_username = []
        no_password = []
        never_logged_in = []
        clean = []

        for a in qs.iterator():
            user = a.student_user
            if user is None:
                no_user.append(a)
                continue

            issues = []
            if not user.is_active:
                inactive.append(a)
                issues.append("inactive")
            if not user.is_student:
                not_is_student.append(a)
                issues.append("is_student=False")
            expected_username = student_portal_username(a.reg_no)
            if expected_username and user.username != expected_username:
                bad_username.append((a, user.username, expected_username))
                issues.append("username mismatch")
            if not user.has_usable_password():
                no_password.append(a)
                issues.append("no usable password")
            if user.last_login is None:
                never_logged_in.append(a)

            if not issues:
                clean.append(a)

        def _line(a):
            name = a.full_name or (a.application.full_name if a.application_id else "")
            return f"      - {a.reg_no or a.id}  {name}"

        self.stdout.write(f"\n  No portal user linked at all: {len(no_user)}")
        for a in no_user[:limit]:
            self.stdout.write(_line(a))

        self.stdout.write(self.style.ERROR(f"\n  Portal user INACTIVE (is_active=False): {len(inactive)}"))
        for a in inactive[:limit]:
            self.stdout.write(_line(a))

        self.stdout.write(
            self.style.ERROR(
                f"\n  is_student=False — BLOCKED by ERP portal-kind gate on "
                f"applications-admin.ndu.ac.ug: {len(not_is_student)}"
            )
        )
        for a in not_is_student[:limit]:
            self.stdout.write(_line(a))

        self.stdout.write(self.style.WARNING(f"\n  Username does not match canonical reg_no format: {len(bad_username)}"))
        for a, actual, expected in bad_username[:limit]:
            self.stdout.write(f"      - {a.reg_no or a.id}  username='{actual}'  expected='{expected}'")

        self.stdout.write(self.style.WARNING(f"\n  No usable password set: {len(no_password)}"))
        for a in no_password[:limit]:
            self.stdout.write(_line(a))

        self.stdout.write(f"\n  Never logged in yet (informational, not necessarily broken): {len(never_logged_in)}")

        self.stdout.write(self.style.SUCCESS(f"\n  Clean (no issues detected): {len(clean)}"))

        if reg_no and total:
            a = qs.first()
            user = a.student_user
            self.stdout.write("\n  --- Detail for this student ---")
            self.stdout.write(f"    reg_no: {a.reg_no}")
            self.stdout.write(f"    student_user_id: {a.student_user_id}")
            if user:
                self.stdout.write(f"    username: {user.username}")
                self.stdout.write(f"    is_active: {user.is_active}")
                self.stdout.write(f"    is_student: {user.is_student}")
                self.stdout.write(f"    is_applicant: {user.is_applicant}")
                self.stdout.write(f"    is_staff: {user.is_staff}")
                self.stdout.write(f"    has_usable_password: {user.has_usable_password()}")
                self.stdout.write(f"    last_login: {user.last_login}")
                self.stdout.write(f"    must_change_password: {getattr(user, 'must_change_password', None)}")

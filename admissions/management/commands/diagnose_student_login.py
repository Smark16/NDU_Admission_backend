"""Diagnose and repair student portal login for a registration number."""
from django.contrib.auth import authenticate
from django.core.management.base import BaseCommand
from django.db.models import Q

from admissions.models import AdmittedStudent
from admissions.student_accounts import (
    DEFAULT_STUDENT_PASSWORD,
    ensure_student_portal_account,
    student_portal_username,
)
from admissions.utils.student_portal_provisioning import (
    StudentPortalProvisioningError,
    assert_student_portal_ready,
    provision_student_portal_on_admission,
)


class Command(BaseCommand):
    help = "Diagnose login for a student registration number and optionally repair."

    def add_arguments(self, parser):
        parser.add_argument("reg_no", type=str, help="Registration number, e.g. 26/2/358/W/0464")
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Provision portal account and reset password to NDU@1234.",
        )
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="With --fix, force password reset even if account exists.",
        )

    def handle(self, *args, **options):
        reg_no = (options["reg_no"] or "").strip()
        portal_username = student_portal_username(reg_no)

        self.stdout.write(f"Registration number: {reg_no}")
        self.stdout.write(f"Portal username:     {portal_username}")

        admission = (
            AdmittedStudent.objects.filter(
                Q(reg_no__iexact=reg_no) | Q(reg_no__iexact=portal_username)
            )
            .select_related("student_user", "application")
            .first()
        )

        if not admission:
            self.stdout.write(self.style.ERROR("No AdmittedStudent found for this reg no."))
            return

        self.stdout.write(f"Admission id:        {admission.id}")
        self.stdout.write(f"Name:                {admission.application.first_name} {admission.application.last_name}")
        self.stdout.write(f"Email:               {admission.application.email}")
        self.stdout.write(f"is_admitted:         {admission.is_admitted}")
        self.stdout.write(f"student_user_id:     {admission.student_user_id}")

        if admission.student_user_id:
            u = admission.student_user
            self.stdout.write(f"User username:       {u.username}")
            self.stdout.write(f"User is_student:     {u.is_student}")
            self.stdout.write(f"User is_active:      {u.is_active}")
            self.stdout.write(f"User is_applicant:   {u.is_applicant}")

        if options["fix"]:
            try:
                if options["reset_password"] and admission.student_user_id:
                    ensure_student_portal_account(admission, reset_password=True)
                else:
                    provision_student_portal_on_admission(
                        admission.id, send_credentials_email=False
                    )
                admission.refresh_from_db()
                self.stdout.write(self.style.SUCCESS("Provisioned / repaired portal account."))
            except StudentPortalProvisioningError as exc:
                self.stdout.write(self.style.ERROR(f"Fix failed: {exc}"))
                return

        try:
            assert_student_portal_ready(admission)
            self.stdout.write(self.style.SUCCESS("Portal account structure: OK"))
        except StudentPortalProvisioningError as exc:
            self.stdout.write(self.style.ERROR(f"Portal account structure: {exc}"))

        for ident in (reg_no, portal_username):
            user = authenticate(username=ident, password=DEFAULT_STUDENT_PASSWORD)
            if user:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Login test OK with username={ident!r} password=NDU@1234"
                    )
                )
                return

        self.stdout.write(
            self.style.ERROR(
                "Login test FAILED with NDU@1234 — run with --fix --reset-password"
            )
        )

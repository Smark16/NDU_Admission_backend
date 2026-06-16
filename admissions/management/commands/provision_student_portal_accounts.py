from django.core.management.base import BaseCommand

from admissions.models import AdmittedStudent
from admissions.student_accounts import ensure_student_portal_account, student_portal_username


class Command(BaseCommand):
    help = "Create or link ERP student portal accounts for admitted students."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset-password",
            action="store_true",
            help="Reset portal passwords to the default first-login password (NDU@1234).",
        )

    def handle(self, *args, **options):
        reset_password = options["reset_password"]
        created = 0
        linked = 0

        for admission in AdmittedStudent.objects.select_related("application__applicant").order_by("id"):
            before_id = admission.student_user_id
            user, _created = ensure_student_portal_account(admission, reset_password=reset_password)
            if user is None:
                continue
            if before_id is None:
                created += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Provisioned {admission.reg_no} as {student_portal_username(admission.reg_no)}"
                    )
                )
            else:
                linked += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Provisioned {created} new account(s); {linked} already linked."
            )
        )

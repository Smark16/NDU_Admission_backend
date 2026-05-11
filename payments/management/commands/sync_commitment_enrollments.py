from django.core.management.base import BaseCommand

from admissions.models import AdmittedStudent

from payments.programme_enrollment_activation import (
    activate_programme_enrollment_after_commitment_payment,
)
from payments.student_portal_finance import commitment_payment_summary


class Command(BaseCommand):
    help = (
        "Activate programme enrollment for admitted students whose completed "
        "UGX tuition payments meet the commitment threshold."
    )

    def handle(self, *args, **options):
        activated = 0
        skipped = 0

        for student in AdmittedStudent.objects.filter(is_admitted=True).iterator():
            if not commitment_payment_summary(student)["commitment_met"]:
                skipped += 1
                continue
            result = activate_programme_enrollment_after_commitment_payment(student)
            if result.get("activated"):
                activated += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{student.student_id}: {result.get('reason')}"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Activated {activated} student(s); skipped {skipped} below threshold."
            )
        )

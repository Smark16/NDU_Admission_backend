from django.core.management.base import BaseCommand

from admissions.models import AdmittedStudent

from payments.programme_enrollment_activation import (
    activate_programme_enrollment_after_commitment_payment,
)
from payments.student_portal_finance import commitment_payment_summary


class Command(BaseCommand):
    help = (
        "Activate programme enrollment and (when enabled) auto-assign current-semester "
        "course units for admitted students who met the commitment fee threshold."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--student-id",
            dest="student_id",
            help="Process one student only (AdmittedStudent.student_id, e.g. 26/1/328/D/0203).",
        )
        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Print a line for every processed student, not only activations.",
        )

    def handle(self, *args, **options):
        student_id = (options.get("student_id") or "").strip()
        verbose = options.get("verbose", False)

        qs = AdmittedStudent.objects.filter(is_admitted=True)
        if student_id:
            qs = qs.filter(student_id=student_id)
            if not qs.exists():
                self.stderr.write(self.style.ERROR(f"No admitted student with student_id={student_id!r}"))
                return

        activated = 0
        skipped = 0
        units_assigned = 0
        processed = 0

        for student in qs.iterator():
            if not commitment_payment_summary(student)["commitment_met"]:
                skipped += 1
                continue

            processed += 1
            result = activate_programme_enrollment_after_commitment_payment(student)
            assigned = int(result.get("course_units_auto_assigned") or 0)
            units_assigned += assigned

            if result.get("activated"):
                activated += 1

            if verbose or result.get("activated") or assigned > 0:
                self.stdout.write(
                    f"{student.student_id}: reason={result.get('reason')} "
                    f"activated={result.get('activated')} "
                    f"units_assigned={assigned} "
                    f"units_in_semester={result.get('course_units_total_in_semester', 0)}"
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {processed} commitment-met student(s); "
                f"activated {activated}; skipped {skipped} below threshold; "
                f"course units assigned this run: {units_assigned}."
            )
        )

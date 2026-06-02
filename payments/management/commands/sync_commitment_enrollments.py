from django.core.management.base import BaseCommand

from admissions.models import AdmittedStudent

from payments.programme_enrollment_activation import (
    activate_programme_enrollment_after_commitment_payment,
)
from payments.student_portal_finance import commitment_payment_summary


def iter_students_in_batches(qs, batch_size=200):
    """
    Walk admitted students without Django server-side cursors.

    .iterator() breaks on some remote Postgres / PgBouncer setups
    (InvalidCursorName).
    """
    last_pk = 0
    while True:
        batch = list(qs.filter(pk__gt=last_pk).order_by("pk")[:batch_size])
        if not batch:
            break
        yield from batch
        last_pk = batch[-1].pk


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
        parser.add_argument(
            "--batch-size",
            type=int,
            default=200,
            help="Students per DB batch when scanning all admitted students (default 200).",
        )

    def handle(self, *args, **options):
        student_id = (options.get("student_id") or "").strip()
        verbose = options.get("verbose", False)
        batch_size = max(1, int(options.get("batch_size") or 200))

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
        zero_semester = 0

        student_iter = qs if student_id else iter_students_in_batches(qs, batch_size=batch_size)

        for student in student_iter:
            if not commitment_payment_summary(student)["commitment_met"]:
                skipped += 1
                continue

            processed += 1
            result = activate_programme_enrollment_after_commitment_payment(student)
            assigned = int(result.get("course_units_auto_assigned") or 0)
            units_assigned += assigned
            in_semester = int(result.get("course_units_total_in_semester") or 0)
            if in_semester == 0:
                zero_semester += 1

            if result.get("activated"):
                activated += 1

            skip_reason = result.get("auto_assign_skip_reason")
            if verbose or result.get("activated") or assigned > 0 or in_semester == 0:
                line = (
                    f"{student.student_id}: reason={result.get('reason')} "
                    f"activated={result.get('activated')} "
                    f"units_assigned={assigned} "
                    f"units_in_semester={in_semester}"
                )
                if skip_reason:
                    line += f" skip={skip_reason}"
                self.stdout.write(line)

        self.stdout.write(
            self.style.SUCCESS(
                f"Done. Processed {processed} commitment-met student(s); "
                f"activated {activated}; skipped {skipped} below threshold; "
                f"course units assigned this run: {units_assigned}; "
                f"with no semester/units to assign: {zero_semester}."
            )
        )

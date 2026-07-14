"""Print which fee rules apply to a student (tuition matrix + scheduled other fees)."""
from django.core.management.base import BaseCommand
from django.db.models import Q

from admissions.models import AdmittedStudent
from payments.student_portal_finance import (
    _applicable_other_schedule_rules,
    _rules_for_student,
    _student_program_batch_id,
    get_admitted_student_for_user,
    other_schedule_rows_and_due_by_currency,
    tuition_structure_dict,
)
from payments.student_fee_pricing import is_international_student


class Command(BaseCommand):
    help = "Diagnose student portal fees for one admitted student (by student_id, reg_no, or username)."

    def add_arguments(self, parser):
        parser.add_argument("lookup", help="student_id, reg_no, or portal username")
        parser.add_argument(
            "--user",
            action="store_true",
            help="Treat lookup as Django username (portal login)",
        )

    def handle(self, *args, **options):
        lookup = (options["lookup"] or "").strip()
        if not lookup:
            self.stderr.write("Provide student_id, reg_no, or username.")
            return

        student = None
        if options["user"]:
            from django.contrib.auth import get_user_model

            User = get_user_model()
            user = User.objects.filter(username=lookup).first()
            if user:
                student = get_admitted_student_for_user(user)
        if student is None:
            student = (
                AdmittedStudent.objects.filter(
                    Q(student_id=lookup) | Q(reg_no=lookup)
                )
                .select_related(
                    "admitted_program",
                    "admitted_batch",
                    "intended_program_batch",
                    "programme_enrollment",
                    "programme_enrollment__program_batch",
                )
                .first()
            )

        if student is None:
            self.stderr.write(self.style.ERROR(f"No admitted student for: {lookup!r}"))
            return

        pb_id = _student_program_batch_id(student)
        ipb = student.intended_program_batch
        enr = getattr(student, "programme_enrollment", None)

        self.stdout.write(self.style.SUCCESS(f"Student: {student.student_id} / {student.reg_no}"))
        self.stdout.write(f"  Programme: {student.admitted_program}")
        self.stdout.write(f"  Admission intake batch: {student.admitted_batch}")
        self.stdout.write(
            f"  Intended cohort: {ipb} (id={student.intended_program_batch_id})"
        )
        if enr:
            self.stdout.write(
                f"  Enrollment cohort: {enr.program_batch} "
                f"(Y{enr.current_year_of_study} T{enr.current_term_number})"
            )
        else:
            self.stdout.write("  Enrollment: (none)")
        self.stdout.write(f"  Resolved cohort for fees: {pb_id}")

        tuition_rules = _rules_for_student(student)
        other_rules = _applicable_other_schedule_rules(student)
        self.stdout.write(f"\nSemester tuition rules ({len(tuition_rules)}):")
        for r in tuition_rules[:20]:
            self.stdout.write(
                f"  - {r.fee_head} {r.amount} {r.currency} | "
                f"batch={r.program_batch_id} sem={r.semester_id}"
            )
        if len(tuition_rules) > 20:
            self.stdout.write(f"  ... and {len(tuition_rules) - 20} more")

        self.stdout.write(f"\nScheduled other fees ({len(other_rules)}):")
        for r in other_rules:
            self.stdout.write(
                f"  - {r.fee_head} {r.amount} | batch={r.program_batch_id} "
                f"Y{r.payable_year_of_study} T{r.payable_term_number}"
            )

        intl = is_international_student(student)
        rows, due = other_schedule_rows_and_due_by_currency(student, intl)
        self.stdout.write(f"\nPortal scheduled_other_fees rows: {len(rows)}")
        for row in rows:
            self.stdout.write(f"  - {row['fee_head']} {row['status']} {row['amount']} {row['currency']}")
        self.stdout.write(f"  Due by currency: {due}")

        struct = tuition_structure_dict(student)
        self.stdout.write(
            f"\nTuition structure items (API): {len(struct['tuition_structure'])} "
            f"total_required={struct['total_required']}"
        )

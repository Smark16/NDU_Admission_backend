"""
Align SPE entry year/term with current for Continuing / Legacy students.

Imported Year 2+ students often kept entry at Y1S1 (stamped on first SPE create),
so prior FeePlanRule terms were re-billed as unpaid carry-forward with no payments.

Also marks admission_fee_paid for continuing migrants — the 150k commitment is
already covered by prior tuition in the old system.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Q
from django.utils import timezone

from Programs.models import StudentProgrammeEnrollment
from admissions.models import AdmittedStudent, Application
from payments.programme_enrollment_activation import (
    activate_programme_enrollment_after_commitment_payment,
)


class Command(BaseCommand):
    help = (
        "Set entry_year/term = current for Continuing/Legacy students and mark "
        "commitment covered by prior tuition (admission_fee_paid)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reg-no",
            action="append",
            dest="reg_nos",
            default=[],
            help="Limit to one or more registration numbers (repeatable).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change without saving.",
        )
        parser.add_argument(
            "--all-legacy",
            action="store_true",
            help="Repair every SPE / student tagged as Continuing / Legacy.",
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])
        reg_nos = [r.strip() for r in (options["reg_nos"] or []) if (r or "").strip()]
        all_legacy = bool(options["all_legacy"])

        if not reg_nos and not all_legacy:
            self.stderr.write(
                "Pass --reg-no … and/or --all-legacy (add --dry-run to preview)."
            )
            return

        qs = StudentProgrammeEnrollment.objects.select_related(
            "student", "student__application"
        ).filter(
            current_year_of_study__isnull=False,
            current_term_number__isnull=False,
        )

        if reg_nos:
            qs = qs.filter(student__reg_no__in=reg_nos)
        if all_legacy:
            qs = qs.filter(
                Q(student__application__source=Application.SOURCE_LEGACY)
                | Q(notes__icontains="Bulk import — continuing")
            )

        entry_updated = 0
        commitment_updated = 0
        activated = 0
        skipped = 0

        for enr in qs.iterator():
            student = enr.student
            cy = int(enr.current_year_of_study or 0)
            ct = int(enr.current_term_number or 0)
            ey = int(enr.entry_year_of_study or 0) if enr.entry_year_of_study else 0
            et = int(enr.entry_term_number or 0) if enr.entry_term_number else 0
            reg = getattr(student, "reg_no", "") or f"id={enr.student_id}"

            if cy < 1 or ct < 1:
                skipped += 1
                continue

            changes = []
            if (ey, et) != (cy, ct):
                changes.append(f"entry Y{ey}T{et}→Y{cy}T{ct}")
            if not student.admission_fee_paid:
                changes.append("commitment=covered (prior tuition)")

            if not changes:
                skipped += 1
                continue

            msg = f"{reg}: " + "; ".join(changes)
            if dry_run:
                self.stdout.write(f"[dry-run] {msg}")
                if (ey, et) != (cy, ct):
                    entry_updated += 1
                if not student.admission_fee_paid:
                    commitment_updated += 1
                continue

            if (ey, et) != (cy, ct):
                enr.entry_year_of_study = cy
                enr.entry_term_number = ct
                enr.save(
                    update_fields=[
                        "entry_year_of_study",
                        "entry_term_number",
                        "updated_at",
                    ]
                )
                entry_updated += 1

            if not student.admission_fee_paid:
                student.admission_fee_paid = True
                student.admission_fee_paid_at = timezone.now()
                student.save(
                    update_fields=[
                        "admission_fee_paid",
                        "admission_fee_paid_at",
                        "updated_at",
                    ]
                )
                commitment_updated += 1

            activation = activate_programme_enrollment_after_commitment_payment(
                AdmittedStudent.objects.get(pk=student.pk)
            )
            if activation.get("activated") or activation.get("reason") == "already_enrolled":
                activated += 1

            self.stdout.write(self.style.SUCCESS(msg))

        self.stdout.write(
            f"{'Would update' if dry_run else 'Updated'} entry={entry_updated}, "
            f"commitment={commitment_updated}"
            + ("" if dry_run else f", activated/enrolled checks={activated}")
            + f"; skipped {skipped}."
        )

"""List or return exemption applications that were submitted without paying the form fee.

  python manage.py return_unpaid_exemption_submissions --dry-run
  python manage.py return_unpaid_exemption_submissions
  python manage.py return_unpaid_exemption_submissions --undo-approved
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.exemption_services import (
    return_unpaid_exemption_submission,
    unpaid_exemption_submissions_qs,
)


class Command(BaseCommand):
    help = (
        "Find exemption requests submitted without a paid EXEMPTION_FORM fee "
        "and return them (reject, without using a student attempt)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="List unpaid submissions only.",
        )
        parser.add_argument(
            "--undo-approved",
            action="store_true",
            help=(
                "Also reverse already-approved unpaid exemptions "
                "(remove curriculum overrides and EXEMPTION_COURSE bills)."
            ),
        )
        parser.add_argument(
            "--id",
            type=int,
            default=None,
            help="Return only this change-request id.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        undo_approved = options["undo_approved"]
        qs = unpaid_exemption_submissions_qs()
        if options["id"]:
            qs = qs.filter(pk=options["id"])
        rows = list(qs)
        if not rows:
            self.stdout.write(self.style.SUCCESS("No unpaid exemption submissions found."))
            return

        self.stdout.write(
            f"{'[DRY-RUN] ' if dry else ''}{len(rows)} unpaid exemption submission(s):"
        )
        for req in rows:
            student = req.admitted_student
            self.stdout.write(
                f"  CR #{req.id} status={req.status} "
                f"{getattr(student, 'reg_no', '')} "
                f"{getattr(student, 'full_name', '')} "
                f"papers={req.exemption_lines.count()}"
            )

        if dry:
            self.stdout.write(
                "Re-run without --dry-run to return pending ones. "
                "Add --undo-approved to reverse approved unpaid exemptions."
            )
            return

        returned = 0
        skipped = 0
        with transaction.atomic():
            for req in rows:
                if req.status == "approved" and not undo_approved:
                    skipped += 1
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skip CR #{req.id}: already approved. Re-run with --undo-approved to reverse."
                        )
                    )
                    continue
                try:
                    result = return_unpaid_exemption_submission(
                        req,
                        actor=None,
                        undo_approved=undo_approved,
                    )
                    returned += 1
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Returned CR #{result['id']} "
                            f"(overrides={result.get('overrides_removed', 0)}, "
                            f"course_charges={result.get('course_charges_removed', 0)})"
                        )
                    )
                except ValueError as exc:
                    skipped += 1
                    self.stdout.write(self.style.WARNING(f"  Skip CR #{req.id}: {exc}"))

        self.stdout.write(
            self.style.SUCCESS(f"Done. Returned {returned}, skipped {skipped}.")
        )
        self.stdout.write(
            "Students can pay Exemption payments on the Course Exemption page, then submit again."
        )

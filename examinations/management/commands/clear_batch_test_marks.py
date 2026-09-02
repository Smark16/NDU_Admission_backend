"""
Clear draft/verified (test) CourseUnitResult rows for a programme batch.

Published results are left alone unless --include-published is passed with
--i-understand-published.

Examples:
  python manage.py clear_batch_test_marks --batch "LLB-377-Main" --dry-run
  python manage.py clear_batch_test_marks --batch "LLB-377-Main"
  python manage.py clear_batch_test_marks --batch "LLB-377-Main" --include-published --i-understand-published
"""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from Programs.models import StudentCourseUnitEnrollment

from examinations.models import CourseUnitResult
from examinations.services.batch_marks_audit import (
    resolve_program_batches,
    results_for_batch,
)


class Command(BaseCommand):
    help = "Delete draft/verified CourseUnitResult rows for a ProgramBatch (published gated)."

    def add_arguments(self, parser):
        parser.add_argument("--batch", default="", help='ProgramBatch name (e.g. "LLB-377-Main").')
        parser.add_argument("--batch-id", type=int, default=None)
        parser.add_argument(
            "--statuses",
            default="draft,verified",
            help="Comma-separated statuses to clear (default: draft,verified).",
        )
        parser.add_argument(
            "--include-published",
            action="store_true",
            help="Also clear published results (requires --i-understand-published).",
        )
        parser.add_argument(
            "--i-understand-published",
            action="store_true",
            help="Required confirmation when clearing published marks.",
        )
        parser.add_argument(
            "--reset-enrollment-status",
            action="store_true",
            default=True,
            help="Reset enrollment completed/failed to enrolled when clearing a published result (default).",
        )
        parser.add_argument(
            "--no-reset-enrollment-status",
            action="store_false",
            dest="reset_enrollment_status",
        )
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            batches = resolve_program_batches(
                batch=options.get("batch") or None,
                batch_id=options.get("batch_id"),
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        statuses = {
            s.strip().lower()
            for s in (options.get("statuses") or "").split(",")
            if s.strip()
        }
        if options.get("include_published"):
            if not options.get("i_understand_published"):
                raise CommandError(
                    "Refusing to clear published marks without --i-understand-published."
                )
            statuses.add(CourseUnitResult.STATUS_PUBLISHED)
        elif CourseUnitResult.STATUS_PUBLISHED in statuses:
            raise CommandError(
                "To clear published results, pass --include-published --i-understand-published."
            )

        allowed = {
            CourseUnitResult.STATUS_DRAFT,
            CourseUnitResult.STATUS_VERIFIED,
            CourseUnitResult.STATUS_PUBLISHED,
        }
        bad = statuses - allowed
        if bad:
            raise CommandError(f"Unknown status values: {sorted(bad)}")
        if not statuses:
            raise CommandError("No statuses selected.")

        dry = bool(options.get("dry_run"))
        reset_enr = bool(options.get("reset_enrollment_status"))

        for batch in batches:
            qs = results_for_batch(batch).filter(status__in=statuses)
            counts = {
                CourseUnitResult.STATUS_DRAFT: qs.filter(status=CourseUnitResult.STATUS_DRAFT).count(),
                CourseUnitResult.STATUS_VERIFIED: qs.filter(status=CourseUnitResult.STATUS_VERIFIED).count(),
                CourseUnitResult.STATUS_PUBLISHED: qs.filter(status=CourseUnitResult.STATUS_PUBLISHED).count(),
            }
            total = sum(counts.values())
            self.stdout.write(
                f"Batch #{batch.id} {batch.program.short_form} — {batch.name}: "
                f"would delete {total} "
                f"(draft={counts['draft']}, verified={counts['verified']}, published={counts['published']})"
            )
            if dry or total == 0:
                continue

            with transaction.atomic():
                published_enrollment_ids = list(
                    qs.filter(status=CourseUnitResult.STATUS_PUBLISHED).values_list(
                        "enrollment_id", flat=True
                    )
                )
                deleted, _ = qs.delete()
                reset_n = 0
                if reset_enr and published_enrollment_ids:
                    reset_n = StudentCourseUnitEnrollment.objects.filter(
                        pk__in=published_enrollment_ids,
                        status__in=("completed", "failed"),
                    ).update(status="enrolled", grade=None)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Deleted {deleted} object(s); reset {reset_n} enrollment status(es)."
                    )
                )

        if dry:
            self.stdout.write(self.style.WARNING("Dry run — no rows deleted."))

"""
Create missing CourseUnits on batch semesters from the curriculum blueprint.

Only touches semesters that already have year_of_study + term_number set.
Does not delete or overwrite existing course units.
"""
from django.core.management.base import BaseCommand, CommandError

from Programs.curriculum_offerings import sync_all_curriculum_offerings


class Command(BaseCommand):
    help = (
        "Sync curriculum onto batch semesters: create CourseUnits that are in the "
        "set curriculum (Year/Term) but still missing on the semester."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--program-id",
            type=int,
            default=None,
            help="Limit sync to one programme id.",
        )
        parser.add_argument(
            "--batch-id",
            type=int,
            default=None,
            help="Limit sync to one program batch id.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report how many offerings would be created without writing.",
        )

    def handle(self, *args, **options):
        program_id = options.get("program_id")
        batch_id = options.get("batch_id")
        dry_run = bool(options.get("dry_run"))

        if program_id and batch_id:
            raise CommandError("Use either --program-id or --batch-id, not both.")

        result = sync_all_curriculum_offerings(
            program_id=program_id,
            batch_id=batch_id,
            dry_run=dry_run,
        )

        self.stdout.write(
            f"programs={result['programs']}  batches={result['batches']}  "
            f"semesters={result['semesters']}  "
            f"{'would_create' if dry_run else 'created'}={result['created']}  "
            f"skipped={result['skipped']}"
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Curriculum sync complete — {result['created']} course unit(s) created."
                )
            )

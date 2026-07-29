"""Create default teaching sections and assign enrollments missing a section."""
from django.core.management.base import BaseCommand

from Programs.teaching_sections import backfill_all_teaching_sections


class Command(BaseCommand):
    help = (
        "Ensure every ProgramBatch has a default teaching section (MAIN) and "
        "assign StudentProgrammeEnrollment rows with null/mismatched sections."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report counts without writing.",
        )

    def handle(self, *args, **options):
        result = backfill_all_teaching_sections(dry_run=bool(options["dry_run"]))
        for key, value in result.items():
            self.stdout.write(f"{key}: {value}")
        if result.get("dry_run"):
            self.stdout.write(self.style.WARNING("Dry run — no changes written."))
        else:
            self.stdout.write(self.style.SUCCESS("Teaching section backfill complete."))

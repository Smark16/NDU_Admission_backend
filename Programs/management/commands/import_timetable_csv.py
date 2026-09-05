"""Import TimetableSession rows from CSV or Excel for one semester.

Usage:
  python manage.py import_timetable_csv --semester-id 12 path/to/slots.xlsx
  python manage.py import_timetable_csv --semester-id 12 path.csv --dry-run
  python manage.py import_timetable_csv --semester-id 12 path.xlsx --no-strict
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from Programs.models import Semester
from Programs.timetable_csv import apply_import, spreadsheet_bytes_to_csv_text


class Command(BaseCommand):
    help = "Import timetable sessions from CSV or Excel (.xlsx) for a semester."

    def add_arguments(self, parser):
        parser.add_argument(
            "csv_path",
            type=str,
            help="Path to UTF-8 CSV or Excel (.xlsx) file (worksheet columns).",
        )
        parser.add_argument(
            "--semester-id",
            type=int,
            required=True,
            help="Target Semester primary key (open Timetable for that cohort).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Validate and report counts without writing sessions.",
        )
        parser.add_argument(
            "--no-strict",
            action="store_true",
            help="Create valid rows even when other rows fail (default is all-or-nothing).",
        )

    def handle(self, *args, **options):
        path = Path(options["csv_path"])
        if not path.is_file():
            raise CommandError(f"File not found: {path}")

        semester = Semester.objects.filter(pk=options["semester_id"], is_active=True).select_related(
            "program_batch", "program_batch__program"
        ).first()
        if semester is None:
            raise CommandError(f"Active semester id={options['semester_id']} not found.")

        try:
            text = spreadsheet_bytes_to_csv_text(path.read_bytes(), path.name)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        strict = not options["no_strict"]
        dry_run = options["dry_run"]
        result = apply_import(semester, text, strict=strict, dry_run=dry_run)

        for err in result.errors:
            self.stderr.write(
                self.style.ERROR(f"Row {err.row} [{err.course_code}]: {err.reason}")
            )
        for warn in result.warnings:
            self.stdout.write(self.style.WARNING(warn))

        if result.errors and result.created == 0:
            raise CommandError(
                f"Import failed ({len(result.errors)} error(s)). "
                "Fix the file or pass --no-strict to skip bad rows."
            )

        label = "Would create" if dry_run else "Created"
        self.stdout.write(
            self.style.SUCCESS(
                f"{label} {result.created} session(s); "
                f"{result.shared_offerings} shared teaching group(s)."
            )
        )

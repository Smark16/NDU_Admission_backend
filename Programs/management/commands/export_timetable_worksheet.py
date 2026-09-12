"""Export a pre-filled timetable worksheet from the database (CSV or Excel).

Usage:
  python manage.py export_timetable_worksheet --semester-id 63 -o worksheet.xlsx
  python manage.py export_timetable_worksheet --semester-id 63 -o worksheet.csv
  python manage.py export_timetable_worksheet --faculty-id 18 --academic-year 2026/2027 \\
      --study-mode Weekend -o science_weekend.xlsx
"""
from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from Programs.models import Semester
from Programs.timetable_csv import build_timetable_worksheet, worksheet_csv_to_xlsx_bytes


class Command(BaseCommand):
    help = (
        "Export a timetable worksheet (STO / cross-cutting / programme-only) "
        "for staff to fill day/time/room in Excel, then import_timetable_csv."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--semester-id",
            type=int,
            default=None,
            help="Anchor semester (also used for default faculty/AY/mode).",
        )
        parser.add_argument("--faculty-id", type=int, default=None)
        parser.add_argument("--academic-year", type=str, default="")
        parser.add_argument(
            "--study-mode",
            type=str,
            default="",
            help="Day / Weekend / Online / Main / Evening (blank = infer or all).",
        )
        parser.add_argument("--campus-id", type=int, default=None)
        parser.add_argument(
            "--expand",
            choices=("faculty", "ay", "none"),
            default="faculty",
            help="faculty=same faculty+AY; ay=same AY only; none=this semester only.",
        )
        parser.add_argument(
            "-o",
            "--output",
            type=str,
            default="",
            help="Write to this path (.xlsx recommended). Default: stdout as CSV.",
        )

    def handle(self, *args, **options):
        semester = None
        if options["semester_id"]:
            semester = (
                Semester.objects.filter(pk=options["semester_id"], is_active=True)
                .select_related("program_batch", "program_batch__program")
                .first()
            )
            if semester is None:
                raise CommandError(f"Active semester id={options['semester_id']} not found.")

        if semester is None and not (
            options["faculty_id"] or options["academic_year"] or options["campus_id"]
        ):
            raise CommandError(
                "Provide --semester-id and/or --faculty-id / --academic-year / --campus-id."
            )

        if options["expand"] == "none" and semester is None:
            raise CommandError("--expand none requires --semester-id.")

        text = build_timetable_worksheet(
            semester=semester,
            faculty_id=options["faculty_id"],
            academic_year=(options["academic_year"] or "").strip(),
            study_mode=(options["study_mode"] or "").strip(),
            campus_id=options["campus_id"],
            expand=options["expand"],
        )

        out = (options["output"] or "").strip()
        if out:
            path = Path(out)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.suffix.lower() in (".xlsx", ".xlsm"):
                try:
                    path.write_bytes(worksheet_csv_to_xlsx_bytes(text))
                except ValueError as exc:
                    raise CommandError(str(exc)) from exc
            else:
                path.write_text(text, encoding="utf-8")
            self.stdout.write(
                self.style.SUCCESS(f"Wrote {path} ({len(text.splitlines())} data lines).")
            )
        else:
            self.stdout.write(text)

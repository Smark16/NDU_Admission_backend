"""CLI: import marks from Excel for a course unit."""
from django.core.management.base import BaseCommand, CommandError

from Programs.models import CourseUnit

from examinations.services.import_marks import import_marks_for_course, parse_marks_workbook


class Command(BaseCommand):
    help = "Import CA/exam marks from Excel (columns: reg_no, ca_mark, exam_mark)."

    def add_arguments(self, parser):
        parser.add_argument("course_unit_id", type=int)
        parser.add_argument("file_path", type=str)

    def handle(self, *args, **options):
        try:
            course_unit = CourseUnit.objects.get(pk=options["course_unit_id"])
        except CourseUnit.DoesNotExist as exc:
            raise CommandError("Course unit not found.") from exc

        with open(options["file_path"], "rb") as f:
            rows = parse_marks_workbook(f.read())

        outcome = import_marks_for_course(course_unit, rows, user=None)
        self.stdout.write(
            self.style.SUCCESS(
                f"Saved {outcome['saved_count']} row(s); {len(outcome['errors'])} error(s)."
            )
        )
        for err in outcome["errors"][:20]:
            self.stdout.write(f"  {err}")

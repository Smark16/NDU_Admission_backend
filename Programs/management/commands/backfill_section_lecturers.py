"""Backfill CourseUnitSectionLecturer ALL-scope rows from CourseUnit.lecturers M2M."""
from django.core.management.base import BaseCommand

from Programs.section_lecturers import backfill_section_lecturers_from_m2m


class Command(BaseCommand):
    help = "Create ALL-section lecturer rows from existing course-unit lecturer M2M."

    def handle(self, *args, **options):
        created = backfill_section_lecturers_from_m2m()
        self.stdout.write(self.style.SUCCESS(f"Created {created} section lecturer row(s)."))

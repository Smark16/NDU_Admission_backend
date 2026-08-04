"""
Contact list: admitted students who still need a teaching subject combination
assigned (programme requires one, none picked yet).

Prints CSV to stdout so it can be redirected straight to a file, e.g.:

    python manage.py list_students_missing_combination > missing_combos.csv
    python manage.py list_students_missing_combination --faculty "Education"
"""
from __future__ import annotations

import csv
import sys

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "CSV contact list of admitted students missing a required teaching subject combination."

    def add_arguments(self, parser):
        parser.add_argument(
            "--faculty",
            default="Education",
            help="Faculty name filter (icontains). Use '' to check every faculty. Default: 'Education'.",
        )

    def handle(self, *args, **options):
        from admissions.admission_specialization import program_requires_admission_specialization
        from admissions.models import AdmittedStudent
        from Programs.models import Program

        faculty_filter = options["faculty"]

        programs_qs = Program.objects.filter(has_specialization=True).exclude(code__istartswith="QA-")
        if faculty_filter:
            programs_qs = programs_qs.filter(faculty__name__icontains=faculty_filter)

        programs = [p for p in programs_qs if program_requires_admission_specialization(p)]

        rows = []
        for program in programs:
            admitted = (
                AdmittedStudent.objects.filter(
                    admitted_program=program,
                    is_admitted=True,
                    admitted_specialization__isnull=True,
                )
                .select_related("application", "admitted_program", "admitted_campus", "admitted_batch")
                .order_by("admission_date")
            )
            for a in admitted:
                rows.append(
                    [
                        a.reg_no or "",
                        a.full_name,
                        a.phone,
                        a.email,
                        a.admitted_program.name if a.admitted_program_id else "",
                        a.admitted_campus.name if a.admitted_campus_id else "",
                        a.study_mode or "",
                        a.admitted_batch.name if a.admitted_batch_id else "",
                        a.admission_date.date().isoformat() if a.admission_date else "",
                    ]
                )

        writer = csv.writer(sys.stdout)
        writer.writerow(
            [
                "reg_no",
                "full_name",
                "phone",
                "email",
                "programme",
                "campus",
                "study_mode",
                "intake",
                "admission_date",
            ]
        )
        for row in rows:
            writer.writerow(row)

        self.stderr.write(self.style.SUCCESS(f"{len(rows)} students missing a combination (written above as CSV)."))

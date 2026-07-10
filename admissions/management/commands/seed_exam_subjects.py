"""Seed O-Level and A-Level exam subjects for applicant forms.

Idempotent: uses get_or_create by subject code.

  python manage.py seed_exam_subjects
"""
from django.core.cache import cache
from django.core.management.base import BaseCommand

from admissions.models import ALevelSubject, OLevelSubject

OLEVEL_SUBJECTS = [
    ("English Language", "ENG"),
    ("Mathematics", "MTH"),
    ("Physics", "PHY"),
    ("Chemistry", "CHE"),
    ("Biology", "BIO"),
    ("History", "HIS"),
    ("Geography", "GEO"),
    ("Agriculture", "AGR"),
    ("Commerce", "COM"),
    ("Computer Studies", "CMP"),
    ("Christian Religious Education", "CRE"),
    ("Fine Art", "FAT"),
    ("Islamic Religious Education", "IRE"),
    ("Kiswahili", "KIS"),
    ("Luganda", "LUG"),
    ("French", "FRE"),
    ("German", "GER"),
    ("Latin", "LAT"),
    ("Literature in English", "LIT"),
    ("Food and Nutrition", "FAN"),
    ("Technical Drawing", "TDR"),
    ("Woodwork", "WOD"),
    ("Metalwork", "MTW"),
    ("Home Economics", "HEC"),
    ("Music", "MUS"),
    ("Physical Education", "PED"),
]

ALEVEL_SUBJECTS = [
    ("Mathematics", "MTH"),
    ("Physics", "PHY"),
    ("Chemistry", "CHE"),
    ("Biology", "BIO"),
    ("History", "HIS"),
    ("Geography", "GEO"),
    ("Economics", "ECO"),
    ("Entrepreneurship", "ENT"),
    ("ICT", "ICT"),
    ("General Paper", "GP"),
    ("Divinity", "DIV"),
    ("Literature in English", "LIT"),
    ("Subsidiary Mathematics", "SUBM"),
    ("Subsidiary ICT", "SUBICT"),
    ("Agriculture", "AGR"),
    ("Art", "ART"),
    ("French", "FRE"),
    ("German", "GER"),
    ("Kiswahili", "KIS"),
    ("Luganda", "LUG"),
    ("Food and Nutrition", "FAN"),
    ("Technical Drawing", "TDR"),
]


class Command(BaseCommand):
    help = "Seed O-Level and A-Level exam subjects (idempotent)."

    def handle(self, *args, **options):
        o_created = 0
        for name, code in OLEVEL_SUBJECTS:
            _, created = OLevelSubject.objects.get_or_create(code=code, defaults={"name": name})
            if created:
                o_created += 1

        a_created = 0
        for name, code in ALEVEL_SUBJECTS:
            _, created = ALevelSubject.objects.get_or_create(code=code, defaults={"name": name})
            if created:
                a_created += 1

        for key in ("all_olevel_subjects_list", "all_alevel_subjects_list"):
            try:
                cache.delete(key)
            except Exception:
                pass

        self.stdout.write(
            self.style.SUCCESS(
                f"O-Level: {OLevelSubject.objects.count()} total ({o_created} new); "
                f"A-Level: {ALevelSubject.objects.count()} total ({a_created} new)."
            )
        )

"""Seed default Ndejje assessment policy and letter-grade scale."""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from admissions.models import AcademicLevel

from examinations.models import (
    AssessmentPolicy,
    AwardClassBand,
    AwardClassificationScheme,
    GradeBand,
    GradeScale,
)


DEFAULT_AWARD_BANDS = [
    ("First Class", "4.40"),
    ("Second Class (Upper)", "3.60"),
    ("Second Class (Lower)", "2.80"),
    ("Pass", "2.00"),
]

DEFAULT_BANDS = [
    ("A", 80, 100, 5.0),
    ("B+", 75, 79.9, 4.5),
    ("B", 70, 74.9, 4.0),
    ("C+", 65, 69.9, 3.5),
    ("C", 60, 64.9, 3.0),
    ("D+", 55, 59.9, 2.5),
    ("D", 50, 54.9, 2.0),
    ("F", 0, 49.9, 0.0),
]


class Command(BaseCommand):
    help = "Create default assessment policy (CA/40, 17.5 sit, 50 pass) and grade scale."

    def handle(self, *args, **options):
        with transaction.atomic():
            policy, created = AssessmentPolicy.objects.update_or_create(
                name="Ndejje default (CA 40 / Exam 60)",
                defaults={
                    "ca_max": Decimal("40"),
                    "exam_weight": Decimal("0.60"),
                    "min_ca_to_sit_exam": Decimal("17.5"),
                    "pass_mark": Decimal("50"),
                    "is_default": True,
                    "is_active": True,
                },
            )
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created policy: {policy.name}"))
            else:
                self.stdout.write(f"Policy exists: {policy.name}")

            for level_name, pass_mark in (
                ("Postgraduate", "60"),
                ("Post Graduate", "60"),
                ("Masters", "60"),
                ("Master", "60"),
            ):
                level = AcademicLevel.objects.filter(name__iexact=level_name).first()
                if not level:
                    continue
                pg_policy, pg_created = AssessmentPolicy.objects.update_or_create(
                    academic_level=level,
                    defaults={
                        "name": f"{level.name} (CA 40 / Exam 60 / pass {pass_mark}%)",
                        "ca_max": Decimal("40"),
                        "exam_weight": Decimal("0.60"),
                        "min_ca_to_sit_exam": Decimal("17.5"),
                        "pass_mark": Decimal(pass_mark),
                        "is_default": False,
                        "is_active": True,
                    },
                )
                action = "Created" if pg_created else "Updated"
                self.stdout.write(self.style.SUCCESS(f"{action} level policy: {pg_policy.name}"))
                break

            scale, sc_created = GradeScale.objects.update_or_create(
                name="Standard letter grades",
                defaults={"is_active": True},
            )
            if sc_created:
                GradeScale.objects.exclude(pk=scale.pk).update(is_active=False)

            for order, (letter, lo, hi, gp) in enumerate(DEFAULT_BANDS):
                GradeBand.objects.update_or_create(
                    grade_scale=scale,
                    letter=letter,
                    defaults={
                        "min_mark": Decimal(str(lo)),
                        "max_mark": Decimal(str(hi)),
                        "grade_point": Decimal(str(gp)),
                        "order": order,
                    },
                )

            self.stdout.write(self.style.SUCCESS(f"Grade scale: {scale.name} ({len(DEFAULT_BANDS)} bands)"))

            award_scheme, aw_created = AwardClassificationScheme.objects.update_or_create(
                name="Standard degree classification",
                defaults={"is_active": True, "academic_level": None},
            )
            if aw_created or award_scheme.academic_level_id is None:
                AwardClassificationScheme.objects.filter(academic_level__isnull=True).exclude(
                    pk=award_scheme.pk
                ).update(is_active=False)
                award_scheme.is_active = True
                award_scheme.save(update_fields=["is_active"])
            for order, (title, min_cgpa) in enumerate(DEFAULT_AWARD_BANDS):
                AwardClassBand.objects.update_or_create(
                    scheme=award_scheme,
                    title=title,
                    defaults={
                        "min_cgpa": Decimal(min_cgpa),
                        "order": order,
                    },
                )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Award scheme: {award_scheme.name} ({len(DEFAULT_AWARD_BANDS)} classes)"
                )
            )

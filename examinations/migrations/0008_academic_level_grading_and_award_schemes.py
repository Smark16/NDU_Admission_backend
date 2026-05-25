# Per-academic-level grade scales and award classification schemes.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0027_academicyear"),
        ("examinations", "0007_alter_assessmentpolicy_academic_level"),
    ]

    operations = [
        migrations.AddField(
            model_name="gradescale",
            name="academic_level",
            field=models.ForeignKey(
                blank=True,
                help_text="When set, applies to programmes at this level. Leave blank for global fallback.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="grade_scales",
                to="admissions.academiclevel",
            ),
        ),
        migrations.AddConstraint(
            model_name="gradescale",
            constraint=models.UniqueConstraint(
                condition=models.Q(("academic_level__isnull", False)),
                fields=("academic_level",),
                name="examinations_unique_grade_scale_per_academic_level",
            ),
        ),
        migrations.CreateModel(
            name="AwardClassificationScheme",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=120)),
                ("is_active", models.BooleanField(db_index=True, default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "academic_level",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="award_classification_schemes",
                        to="admissions.academiclevel",
                    ),
                ),
            ],
            options={
                "verbose_name": "Award classification scheme",
                "ordering": ["name"],
            },
        ),
        migrations.CreateModel(
            name="AwardClassBand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("title", models.CharField(help_text="e.g. First Class, Second Class (Upper)", max_length=80)),
                (
                    "min_cgpa",
                    models.DecimalField(
                        decimal_places=2,
                        help_text="Award applies when CGPA is at or above this value.",
                        max_digits=4,
                    ),
                ),
                ("order", models.PositiveSmallIntegerField(default=0)),
                (
                    "scheme",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bands",
                        to="examinations.awardclassificationscheme",
                    ),
                ),
            ],
            options={
                "ordering": ["-min_cgpa", "order"],
            },
        ),
        migrations.AddConstraint(
            model_name="awardclassificationscheme",
            constraint=models.UniqueConstraint(
                condition=models.Q(("academic_level__isnull", False)),
                fields=("academic_level",),
                name="examinations_unique_award_scheme_per_academic_level",
            ),
        ),
    ]

# Generated manually for per-academic-level assessment policies.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0027_academicyear"),
        ("examinations", "0005_seed_examination_lighter_roles"),
    ]

    operations = [
        migrations.AddField(
            model_name="assessmentpolicy",
            name="academic_level",
            field=models.ForeignKey(
                blank=True,
                help_text="When set, applies to all programmes at this academic level.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="assessment_policies",
                to="admissions.academiclevel",
            ),
        ),
        migrations.AddConstraint(
            model_name="assessmentpolicy",
            constraint=models.UniqueConstraint(
                condition=models.Q(("academic_level__isnull", False)),
                fields=("academic_level",),
                name="examinations_unique_policy_per_academic_level",
            ),
        ),
    ]

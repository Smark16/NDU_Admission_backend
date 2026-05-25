# Examination card token for QR verification at block entry.

import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0027_academicyear"),
        ("examinations", "0009_alter_awardclassband_id_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ExamCardToken",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                (
                    "verification_code",
                    models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True),
                ),
                ("exam_period_label", models.CharField(blank=True, default="", max_length=120)),
                ("issued_at", models.DateTimeField(auto_now_add=True)),
                ("expires_at", models.DateTimeField(blank=True, null=True)),
                ("is_revoked", models.BooleanField(default=False)),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="exam_card_tokens",
                        to="admissions.admittedstudent",
                    ),
                ),
            ],
            options={
                "ordering": ["-issued_at"],
            },
        ),
    ]

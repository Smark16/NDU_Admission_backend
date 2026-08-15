# Merge parallel 0062/0063 branches (academic departments vs email/index rename).

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0063_academic_department_head"),
        (
            "admissions",
            "0063_rename_admissions__student_b8e2a1_idx_admissions__student_cd7e16_idx_and_more",
        ),
    ]

    operations = []

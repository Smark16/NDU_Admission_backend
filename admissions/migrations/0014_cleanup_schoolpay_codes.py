from django.db import migrations, models
from django.db.models import Q


def clear_provisional_schoolpay_codes(apps, schema_editor):
    AdmittedStudent = apps.get_model("admissions", "AdmittedStudent")
    for row in AdmittedStudent.objects.filter(is_registered_with_schoolpay=False):
        if row.schoolpay_code and row.schoolpay_code == row.reg_no:
            row.schoolpay_code = None
            row.save(update_fields=["schoolpay_code"])


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0013_alter_admittedstudent_schoolpay_code_and_more"),
    ]

    operations = [
        migrations.RunPython(clear_provisional_schoolpay_codes, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="admittedstudent",
            constraint=models.UniqueConstraint(
                condition=Q(schoolpay_code__isnull=False) & ~Q(schoolpay_code=""),
                fields=("schoolpay_code",),
                name="unique_admittedstudent_schoolpay_code",
            ),
        ),
    ]

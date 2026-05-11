from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0011_merge_20260511_1015"),
    ]

    operations = [
        migrations.AddField(
            model_name="admittedstudent",
            name="is_registered_with_schoolpay",
            field=models.BooleanField(
                default=False,
                help_text="True after the student has been synced with the SchoolPay gateway.",
            ),
        ),
    ]

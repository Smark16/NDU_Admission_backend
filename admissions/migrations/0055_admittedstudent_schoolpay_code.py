from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0054_physical_document_verification"),
    ]

    operations = [
        migrations.AddField(
            model_name="admittedstudent",
            name="schoolpay_code",
            field=models.CharField(blank=True, db_index=True, max_length=100, null=True, unique=True),
        ),
    ]


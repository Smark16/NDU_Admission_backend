import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("admissions", "0062_academic_department"),
    ]

    operations = [
        migrations.AddField(
            model_name="academicdepartment",
            name="head_of_department",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="headed_academic_departments",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]

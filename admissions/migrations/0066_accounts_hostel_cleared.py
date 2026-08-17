from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("admissions", "0065_exemption_form_draft"),
    ]

    operations = [
        migrations.AddField(
            model_name="admittedstudent",
            name="accounts_hostel_cleared",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "Accounts cleared this student for hostel assignment only. "
                    "Does not unlock course registration or the registration card."
                ),
            ),
        ),
        migrations.AddField(
            model_name="admittedstudent",
            name="accounts_hostel_cleared_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="admittedstudent",
            name="accounts_hostel_cleared_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="accounts_hostel_clearances",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="admittedstudent",
            name="accounts_hostel_clearance_notes",
            field=models.TextField(blank=True),
        ),
    ]

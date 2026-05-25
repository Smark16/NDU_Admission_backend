from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0027_alter_systemsettings_id_card_templates"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="allow_multi_campus_per_day",
            field=models.BooleanField(
                default=False,
                help_text="If false, timetable blocks same lecturer on two campuses in one day.",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="primary_campus",
            field=models.ForeignKey(
                blank=True,
                help_text="Main teaching campus (used for timetable campus rules).",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="primary_staff",
                to="accounts.campus",
            ),
        ),
    ]

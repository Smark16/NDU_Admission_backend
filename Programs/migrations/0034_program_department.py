from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0067_idcardpdftemplate_audience"),
        ("Programs", "0033_alter_lectureattendancerecord_marked_via"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="department",
            field=models.ForeignKey(
                blank=True,
                help_text="Teaching department that owns this programme.",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="programs",
                to="admissions.academicdepartment",
            ),
        ),
    ]

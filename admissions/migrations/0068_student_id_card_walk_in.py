from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("admissions", "0067_idcardpdftemplate_audience"),
    ]

    operations = [
        migrations.AlterField(
            model_name="studentidcard",
            name="admitted_student",
            field=models.ForeignKey(
                blank=True,
                help_text="Null for walk-in IDs printed without an ERP student record.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="id_cards",
                to="admissions.admittedstudent",
            ),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_campus",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_full_name",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_gender",
            field=models.CharField(blank=True, default="", max_length=20),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_photo",
            field=models.ImageField(
                blank=True,
                help_text="Passport photo for walk-in cards (not linked to Application).",
                null=True,
                upload_to="id_cards/walk_in/",
            ),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_programme",
            field=models.CharField(blank=True, default="", max_length=200),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_reg_no",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_student_no",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="studentidcard",
            name="walk_in_validity_years",
            field=models.PositiveSmallIntegerField(
                default=4,
                help_text="Programme length used for expiry on walk-in cards.",
            ),
        ),
    ]

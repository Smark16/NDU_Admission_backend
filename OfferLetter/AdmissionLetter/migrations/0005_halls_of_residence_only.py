from django.db import migrations, models

# Official University Halls of Residence. Hostel buildings imported into the
# Hostel module must never be selectable on admission letter templates.
OFFICIAL_HALLS = {"AKIIBUA", "NJUKI", "MUTEESA", "KAKUNGULU", "YOKANA"}


def clear_hostel_values(apps, schema_editor):
    OfferLetterTemplate = apps.get_model("AdmissionLetter", "OfferLetterTemplate")
    (
        OfferLetterTemplate.objects.exclude(hall_of_residence__in=OFFICIAL_HALLS)
        .exclude(hall_of_residence__isnull=True)
        .exclude(hall_of_residence="")
        .update(hall_of_residence="")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("AdmissionLetter", "0004_align_hostel_hall_choices"),
    ]

    operations = [
        migrations.AlterField(
            model_name="offerlettertemplate",
            name="hall_of_residence",
            field=models.CharField(
                blank=True,
                choices=[
                    ("AKIIBUA", "Akiibua"),
                    ("NJUKI", "Njuki"),
                    ("MUTEESA", "Muteesa"),
                    ("KAKUNGULU", "Kakungulu"),
                    ("YOKANA", "Yokana"),
                    ("RANDOM", "Assign Randomly"),
                ],
                max_length=200,
                null=True,
            ),
        ),
        migrations.RunPython(clear_hostel_values, migrations.RunPython.noop),
    ]

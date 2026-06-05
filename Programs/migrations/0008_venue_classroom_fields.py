from django.db import migrations, models
import django.db.models.deletion


def assign_default_campus(apps, schema_editor):
    Venue = apps.get_model("Programs", "Venue")
    Campus = apps.get_model("accounts", "Campus")
    default = Campus.objects.order_by("id").first()
    if not default:
        return
    Venue.objects.filter(campus_id__isnull=True).update(campus_id=default.id)


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0001_initial"),
        ("Programs", "0007_timetable"),
    ]

    operations = [
        migrations.AddField(
            model_name="venue",
            name="building",
            field=models.CharField(blank=True, default="", max_length=80),
        ),
        migrations.AddField(
            model_name="venue",
            name="code",
            field=models.CharField(
                blank=True,
                default="",
                help_text="Short code unique per campus, e.g. MAIN-LT1.",
                max_length=40,
            ),
        ),
        migrations.AddField(
            model_name="venue",
            name="room_type",
            field=models.CharField(
                choices=[
                    ("lecture", "Lecture room"),
                    ("lab", "Laboratory"),
                    ("hall", "Hall / auditorium"),
                    ("office", "Office / seminar"),
                    ("other", "Other"),
                ],
                default="lecture",
                max_length=20,
            ),
        ),
        migrations.RunPython(assign_default_campus, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="venue",
            name="campus",
            field=models.ForeignKey(
                help_text="Campus where this room is located (required for new rows).",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="venues",
                to="accounts.campus",
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.UniqueConstraint(
                fields=("campus", "name"), name="programs_venue_unique_name_per_campus"
            ),
        ),
        migrations.AddConstraint(
            model_name="venue",
            constraint=models.UniqueConstraint(
                condition=models.Q(("code", ""), _negated=True),
                fields=("campus", "code"),
                name="programs_venue_unique_code_per_campus",
            ),
        ),
    ]

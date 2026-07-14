from django.db import migrations

NEW_NAME = "NDEJJE UNIVERSITY"
OLD_NAME = "NDEJJE UNIVERSITY STEWARD"


def rename_university(apps, schema_editor):
    SystemSettings = apps.get_model("accounts", "SystemSettings")
    for obj in SystemSettings.objects.all():
        current = (obj.university_name or "").strip()
        if not current or current == OLD_NAME or "STEWARD" in current.upper():
            obj.university_name = NEW_NAME
            obj.save(update_fields=["university_name"])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0040_ar_data_clerk_role"),
    ]

    operations = [
        migrations.RunPython(rename_university, noop_reverse),
    ]
